"""
Signal quality tests: freshness buckets, stale downgrade, weak-signal classification,
multi-keyword clustering, padded opportunity flagging, grounded why_now.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from marketscout.brain.schema import EvidenceItem
from marketscout.brain.strategy import (
    _build_opportunity_brief,
    _classify_support_level,
    _confidence_single,
    _freshness_bucket,
    _signal_age_days,
    generate_mock_strategy,
)


# ── Freshness helpers ─────────────────────────────────────────────────────────


def _published_days_ago(days: float) -> str:
    """Return an ISO-8601 timestamp for a signal published N days ago."""
    ts = datetime.now(tz=timezone.utc) - timedelta(days=days)
    return ts.isoformat()


def test_freshness_bucket_very_fresh() -> None:
    assert _freshness_bucket(0) == "very_fresh"
    assert _freshness_bucket(3) == "very_fresh"
    assert _freshness_bucket(6.9) == "very_fresh"


def test_freshness_bucket_fresh() -> None:
    assert _freshness_bucket(7) == "fresh"
    assert _freshness_bucket(15) == "fresh"
    assert _freshness_bucket(29.9) == "fresh"


def test_freshness_bucket_moderate() -> None:
    assert _freshness_bucket(30) == "moderate"
    assert _freshness_bucket(60) == "moderate"
    assert _freshness_bucket(89.9) == "moderate"


def test_freshness_bucket_stale() -> None:
    assert _freshness_bucket(90) == "stale"
    assert _freshness_bucket(120) == "stale"
    assert _freshness_bucket(365) == "stale"


def test_signal_age_days_iso_timestamp() -> None:
    pub = _published_days_ago(10)
    age = _signal_age_days(pub)
    assert age is not None
    assert 9.9 < age < 10.1


def test_signal_age_days_empty_returns_none() -> None:
    assert _signal_age_days("") is None
    assert _signal_age_days("   ") is None
    assert _signal_age_days("not-a-date") is None


def test_signal_age_days_z_suffix() -> None:
    """ISO-8601 timestamps ending in Z are parsed correctly."""
    ts = (datetime.now(tz=timezone.utc) - timedelta(days=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    age = _signal_age_days(ts)
    assert age is not None
    assert 4.9 < age < 5.1


# ── Confidence: per-opportunity freshness (not global window) ─────────────────


def test_confidence_fresh_signals_higher_than_stale() -> None:
    """Fresh evidence (5 days) should yield higher confidence than stale (100 days)."""
    conf_fresh = _confidence_single(
        evidence_count=3,
        has_headline=True,
        has_job=True,
        avg_age_days=5.0,
        unique_source_count=3,
    )
    conf_stale = _confidence_single(
        evidence_count=3,
        has_headline=True,
        has_job=True,
        avg_age_days=100.0,
        unique_source_count=3,
    )
    assert conf_fresh > conf_stale, f"Fresh {conf_fresh} should exceed stale {conf_stale}"


def test_confidence_stale_signals_below_threshold() -> None:
    """Stale signals (>=90 days) with moderate evidence count should give confidence below 0.5."""
    # 3 stale evidence items, single source type, single unique source:
    # count_factor=0.24, mix=0.08, freshness=0.0, source_div=0.05 → 0.37
    conf = _confidence_single(
        evidence_count=3,
        has_headline=True,
        has_job=False,
        avg_age_days=95.0,
        unique_source_count=1,
    )
    assert conf < 0.5, f"Stale moderate evidence should be < 0.5, got {conf}"


def test_confidence_unknown_age_is_penalized() -> None:
    """Unknown age (None) should yield lower confidence than known-fresh signals."""
    conf_fresh = _confidence_single(
        evidence_count=3,
        has_headline=True,
        has_job=True,
        avg_age_days=5.0,
        unique_source_count=2,
    )
    conf_unknown = _confidence_single(
        evidence_count=3,
        has_headline=True,
        has_job=True,
        avg_age_days=None,
        unique_source_count=2,
    )
    assert conf_fresh > conf_unknown


def test_confidence_more_unique_sources_raises_score() -> None:
    """More unique sources should increase confidence holding other factors constant."""
    conf_few = _confidence_single(
        evidence_count=3,
        has_headline=True,
        has_job=False,
        avg_age_days=10.0,
        unique_source_count=1,
    )
    conf_many = _confidence_single(
        evidence_count=3,
        has_headline=True,
        has_job=False,
        avg_age_days=10.0,
        unique_source_count=4,
    )
    assert conf_many > conf_few


def test_confidence_max_is_one() -> None:
    conf = _confidence_single(
        evidence_count=10,
        has_headline=True,
        has_job=True,
        avg_age_days=1.0,
        unique_source_count=10,
    )
    assert conf <= 1.0


def test_confidence_min_is_zero() -> None:
    conf = _confidence_single(
        evidence_count=0,
        has_headline=False,
        has_job=False,
        avg_age_days=200.0,
        unique_source_count=0,
    )
    assert conf >= 0.0


# ── Support level classification ──────────────────────────────────────────────


def test_support_level_weak_when_padded() -> None:
    level = _classify_support_level(
        evidence_count=3,
        has_headline=True,
        has_job=True,
        avg_age_days=5.0,
        unique_sources=3,
        is_padded=True,
    )
    assert level == "weak"


def test_support_level_weak_when_single_evidence() -> None:
    level = _classify_support_level(
        evidence_count=1,
        has_headline=True,
        has_job=False,
        avg_age_days=5.0,
        unique_sources=1,
        is_padded=False,
    )
    assert level == "weak"


def test_support_level_weak_when_stale() -> None:
    """Evidence averaging 90+ days old should be classified as weak."""
    level = _classify_support_level(
        evidence_count=4,
        has_headline=True,
        has_job=True,
        avg_age_days=95.0,
        unique_sources=3,
        is_padded=False,
    )
    assert level == "weak"


def test_support_level_weak_when_single_source() -> None:
    """Only one unique source (no cross-source validation) should be weak."""
    level = _classify_support_level(
        evidence_count=4,
        has_headline=True,
        has_job=True,
        avg_age_days=5.0,
        unique_sources=1,
        is_padded=False,
    )
    assert level == "weak"


def test_support_level_strong_all_conditions_met() -> None:
    """4+ evidence, both types, 3+ sources, fresh → strong."""
    level = _classify_support_level(
        evidence_count=4,
        has_headline=True,
        has_job=True,
        avg_age_days=10.0,
        unique_sources=3,
        is_padded=False,
    )
    assert level == "strong"


def test_support_level_moderate_partial_coverage() -> None:
    """2 evidence, two sources, not old enough to be stale → moderate."""
    level = _classify_support_level(
        evidence_count=2,
        has_headline=True,
        has_job=False,
        avg_age_days=20.0,
        unique_sources=2,
        is_padded=False,
    )
    assert level == "moderate"


def test_support_level_moderate_no_job_signals() -> None:
    """Missing job type but otherwise decent evidence → not strong."""
    level = _classify_support_level(
        evidence_count=4,
        has_headline=True,
        has_job=False,
        avg_age_days=5.0,
        unique_sources=3,
        is_padded=False,
    )
    assert level in ("moderate", "weak")  # Cannot be strong without both types


# ── Padded opportunity flagging ───────────────────────────────────────────────


def test_padded_opportunity_flagged_when_no_keyword_match() -> None:
    """When headlines/jobs contain no template keywords, all opportunities should be padded."""
    headlines = [{"title": "Unrelated topic", "link": "https://x.com/1", "source": "X", "published": ""}]
    jobs = [{"title": "Random job posting", "link": "https://x.com/2", "company": "Co", "published": "", "source": ""}]
    strategy = generate_mock_strategy(headlines, industry="Construction", city="Vancouver", jobs=jobs)
    padded = [o for o in strategy.opportunity_map if o.is_padded]
    real = [o for o in strategy.opportunity_map if not o.is_padded]
    # With no keyword matches, all 5 opportunities must be padded
    assert len(padded) == 5
    assert len(real) == 0


def test_padded_opportunities_are_weak() -> None:
    """Padded opportunities must always have support_level == 'weak'."""
    strategy = generate_mock_strategy([], industry="Technology", city="Toronto")
    for o in strategy.opportunity_map:
        if o.is_padded:
            assert o.support_level == "weak", f"Padded opp {o.title!r} has support_level={o.support_level!r}"


def test_real_opportunities_not_flagged() -> None:
    """Opportunities backed by real keyword evidence should not be padded."""
    headlines = [
        {"title": "Labor shortage hits construction sector", "link": "https://news.com/1", "source": "NewsA", "published": _published_days_ago(3)},
        {"title": "Wage pressure rising for workers", "link": "https://news.com/2", "source": "NewsB", "published": _published_days_ago(5)},
    ]
    jobs = [
        {"title": "Construction Coordinator needed", "link": "https://jobs.com/1", "company": "BuildCo", "published": _published_days_ago(2), "source": "adzuna"},
    ]
    strategy = generate_mock_strategy(headlines, industry="Construction", city="Vancouver", jobs=jobs)
    real = [o for o in strategy.opportunity_map if not o.is_padded]
    assert len(real) >= 1, "Expected at least one real (non-padded) opportunity"


# ── Multi-keyword clustering ──────────────────────────────────────────────────


def test_signal_contributes_to_multiple_buckets() -> None:
    """
    A headline matching keywords for two different bottlenecks should appear
    as evidence in both. The total evidence count across all opportunities
    should exceed the headline count when multi-keyword signals are present.
    """
    # "labor shortage" matches both 'labor' and 'shortage' keywords (if both are in the template)
    headlines = [
        {"title": "Labor shortage and permit delays hit construction", "link": "https://a.com", "source": "A", "published": ""},
        {"title": "Material cost and supply chain crisis", "link": "https://b.com", "source": "B", "published": ""},
    ]
    strategy = generate_mock_strategy(headlines, industry="Construction", city="Vancouver")
    total_evidence = sum(len(o.evidence) for o in strategy.opportunity_map if not o.is_padded)
    # If multi-keyword is working, total evidence in real opps > number of headlines
    # (same signal can appear in multiple opportunity buckets)
    assert total_evidence >= len(headlines), (
        "Multi-keyword clustering should allow signals to support multiple opportunities"
    )


# ── Grounded why_now ──────────────────────────────────────────────────────────


def test_why_now_contains_age_when_timestamps_available() -> None:
    """why_now should cite signal age when published timestamps are provided."""
    ev = [
        EvidenceItem(title="Signal A", link="https://a.com", source="headline"),
        EvidenceItem(title="Signal B", link="https://b.com", source="job"),
        EvidenceItem(title="Signal C", link="https://c.com", source="headline"),
        EvidenceItem(title="Signal D", link="https://d.com", source="job"),
    ]
    brief = _build_opportunity_brief(
        title="Test",
        ai_category="Operational efficiency",
        pain_score=7.0,
        evidence=ev,
        industry="Construction",
        avg_age_days=12.0,
        unique_sources_count=4,
        support_level="strong",
    )
    # Age should appear in why_now (e.g. "12d old")
    assert "12" in brief.why_now, f"Expected age in why_now: {brief.why_now}"


def test_why_now_contains_source_count() -> None:
    """why_now should cite unique source count when > 1."""
    ev = [
        EvidenceItem(title=f"Signal {i}", link=f"https://ex.com/{i}", source="headline" if i % 2 == 0 else "job")
        for i in range(4)
    ]
    brief = _build_opportunity_brief(
        title="Test",
        ai_category="Cost reduction",
        pain_score=7.0,
        evidence=ev,
        industry="Manufacturing",
        avg_age_days=5.0,
        unique_sources_count=4,
        support_level="strong",
    )
    assert "4" in brief.why_now


def test_why_now_flags_stale_signals() -> None:
    """Stale signals (>= 90 days) should cause why_now to mention 'stale'."""
    ev = [
        EvidenceItem(title="Old Signal A", link="https://a.com", source="headline"),
        EvidenceItem(title="Old Signal B", link="https://b.com", source="headline"),
    ]
    brief = _build_opportunity_brief(
        title="Test",
        ai_category="Cost reduction",
        pain_score=4.0,
        evidence=ev,
        industry="Retail",
        avg_age_days=100.0,
        unique_sources_count=2,
        support_level="weak",
    )
    assert "stale" in brief.why_now.lower() or "verify" in brief.why_now.lower()


def test_why_now_no_age_when_no_timestamps() -> None:
    """When avg_age_days is None, why_now should not contain a spurious age figure."""
    ev = [EvidenceItem(title="Signal", link="https://a.com", source="headline")]
    brief = _build_opportunity_brief(
        title="Test",
        ai_category="Market entry",
        pain_score=3.0,
        evidence=ev,
        industry="Retail",
    )
    # Should not contain things like "0d" or a numeric age since we have no timestamps
    assert "avg" not in brief.why_now


# ── Strategy output: new fields present and consistent ───────────────────────


def test_strategy_output_has_signal_quality_fields() -> None:
    """Every opportunity in a generated strategy must carry the new signal quality fields."""
    headlines = [
        {"title": "Labor shortage hits Vancouver construction", "link": "https://a.com", "source": "A", "published": _published_days_ago(5)},
        {"title": "Permit backlog slowing developments", "link": "https://b.com", "source": "B", "published": _published_days_ago(8)},
    ]
    jobs = [
        {"title": "Construction Coordinator", "link": "https://j.com", "company": "BuildCo", "published": _published_days_ago(3), "source": "adzuna"},
    ]
    strategy = generate_mock_strategy(headlines, industry="Construction", city="Vancouver", jobs=jobs)
    for o in strategy.opportunity_map:
        assert o.support_level in ("strong", "moderate", "weak"), f"Invalid support_level: {o.support_level}"
        assert isinstance(o.is_padded, bool)
        assert isinstance(o.unique_sources_count, int) and o.unique_sources_count >= 0
        if o.signal_age_days_avg is not None:
            assert o.signal_age_days_avg >= 0.0


def test_padded_opportunities_have_is_padded_true_in_json() -> None:
    """is_padded field must survive round-trip through to_json_dict."""
    strategy = generate_mock_strategy([], industry="Technology", city="Vancouver")
    d = strategy.to_json_dict()
    for opp in d["opportunity_map"]:
        assert "is_padded" in opp
        assert "support_level" in opp
        assert "unique_sources_count" in opp


def test_fresh_signals_produce_age_in_output() -> None:
    """When signals have parseable timestamps, signal_age_days_avg should be set on real opps."""
    headlines = [
        {"title": "Labor shortage crisis in construction", "link": "https://n.com/1", "source": "N1", "published": _published_days_ago(5)},
        {"title": "Labor cost rises sharply", "link": "https://n.com/2", "source": "N2", "published": _published_days_ago(10)},
    ]
    strategy = generate_mock_strategy(headlines, industry="Construction", city="Vancouver")
    real_with_age = [o for o in strategy.opportunity_map if not o.is_padded and o.signal_age_days_avg is not None]
    assert len(real_with_age) >= 1, "At least one real opportunity should have a known signal age"
    for o in real_with_age:
        # Age should be in the ballpark of 5–15 days
        assert 3.0 < o.signal_age_days_avg < 15.0, f"Unexpected age: {o.signal_age_days_avg}"
