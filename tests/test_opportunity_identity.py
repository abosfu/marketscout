"""Tests for Phase 3: Opportunity Identity + Actionability.

Covers:
  - _make_trend_key stability, city stripping, padded vs real prefixes
  - _classify_recommendation rules for all 4 states
  - _classify_opportunity_type mapping
  - _build_problem_specific_commercial_angle keyword routing
  - Quality-aware suggested_next_step in _build_opportunity_brief
  - New fields (trend_key, recommendation, opportunity_type) in strategy output
  - DB persistence of trend_key and recommendation
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
from pathlib import Path

import pytest

from marketscout.brain.strategy import (
    _build_opportunity_brief,
    _build_problem_specific_commercial_angle,
    _classify_opportunity_type,
    _classify_recommendation,
    _make_trend_key,
    _slugify,
)
from marketscout.brain.schema import EvidenceItem, StrategyOutput
from marketscout.db import get_connection, save_run, compare_runs


# ── Helpers ────────────────────────────────────────────────────────────────────

def _evidence(n: int = 2, source: str = "headline") -> list[EvidenceItem]:
    return [EvidenceItem(title=f"title {i}", link=f"http://x.com/{i}", source=source) for i in range(n)]


def _mixed_evidence(n_h: int = 2, n_j: int = 2) -> list[EvidenceItem]:
    ev = [EvidenceItem(title=f"headline {i}", link=f"http://h.com/{i}", source="headline") for i in range(n_h)]
    ev += [EvidenceItem(title=f"job {i}", link=f"http://j.com/{i}", source="job") for i in range(n_j)]
    return ev


# ── _slugify ──────────────────────────────────────────────────────────────────

def test_slugify_basic():
    assert _slugify("Operational Efficiency") == "operational_efficiency"


def test_slugify_strips_leading_trailing_underscores():
    assert not _slugify("--foo--").startswith("_")
    assert not _slugify("--foo--").endswith("_")


def test_slugify_collapses_special_chars():
    assert _slugify("foo & bar!") == "foo_bar"


# ── _make_trend_key ───────────────────────────────────────────────────────────

def test_make_trend_key_real_format():
    key = _make_trend_key("Labor shortages and wage pressure", "Operational efficiency", is_padded=False)
    assert key.startswith("operational_efficiency::")
    assert "labor" in key


def test_make_trend_key_padded_prefix():
    key = _make_trend_key("Market dynamics in Vancouver", "Market entry", is_padded=True)
    assert key.startswith("padded::")


def test_make_trend_key_strips_city_from_padded():
    key = _make_trend_key("Market dynamics in Vancouver", "Market entry", is_padded=True)
    assert "vancouver" not in key.lower()


def test_make_trend_key_city_not_stripped_from_real():
    key = _make_trend_key("Market dynamics in Vancouver", "Market entry", is_padded=False)
    # Real keys use ai_category prefix and keep the full problem slug
    assert key.startswith("market_entry::")


def test_make_trend_key_stable():
    """Same inputs always produce the same key."""
    k1 = _make_trend_key("Labor shortages", "Operational efficiency", is_padded=False)
    k2 = _make_trend_key("Labor shortages", "Operational efficiency", is_padded=False)
    assert k1 == k2


def test_make_trend_key_different_problems():
    k1 = _make_trend_key("Labor shortages", "Operational efficiency", is_padded=False)
    k2 = _make_trend_key("Supply chain delays", "Operational efficiency", is_padded=False)
    assert k1 != k2


def test_make_trend_key_padded_vs_real_differ():
    k_real = _make_trend_key("Labor shortages", "Operational efficiency", is_padded=False)
    k_pad = _make_trend_key("Labor shortages", "Operational efficiency", is_padded=True)
    assert k_real != k_pad
    assert k_pad.startswith("padded::")


# ── _classify_recommendation ──────────────────────────────────────────────────

def test_recommendation_padded_always_deprioritize():
    assert _classify_recommendation("strong", 0.9, 9.0, is_padded=True, avg_age_days=5.0) == "deprioritize"


def test_recommendation_weak_low_conf_deprioritize():
    assert _classify_recommendation("weak", 0.20, 7.0, is_padded=False, avg_age_days=10.0) == "deprioritize"


def test_recommendation_stale_low_pain_deprioritize():
    assert _classify_recommendation("moderate", 0.50, 3.0, is_padded=False, avg_age_days=95.0) == "deprioritize"


def test_recommendation_pursue_now_all_conditions_met():
    result = _classify_recommendation("strong", 0.70, 7.5, is_padded=False, avg_age_days=10.0)
    assert result == "pursue_now"


def test_recommendation_pursue_now_blocked_by_stale():
    # Strong + high conf + high pain but signal is stale (>= 30d)
    result = _classify_recommendation("strong", 0.70, 7.5, is_padded=False, avg_age_days=35.0)
    assert result != "pursue_now"


def test_recommendation_pursue_now_blocked_by_low_confidence():
    result = _classify_recommendation("strong", 0.45, 7.5, is_padded=False, avg_age_days=10.0)
    assert result != "pursue_now"


def test_recommendation_validate_further_moderate_support():
    result = _classify_recommendation("moderate", 0.40, 5.0, is_padded=False, avg_age_days=20.0)
    assert result == "validate_further"


def test_recommendation_validate_further_strong_not_fresh_enough():
    # Strong support but stale — pursue_now blocked; enough confidence for validate_further
    result = _classify_recommendation("strong", 0.50, 5.0, is_padded=False, avg_age_days=45.0)
    assert result == "validate_further"


def test_recommendation_monitor_low_everything():
    result = _classify_recommendation("moderate", 0.20, 3.0, is_padded=False, avg_age_days=20.0)
    assert result == "monitor"


def test_recommendation_monitor_unknown_age():
    result = _classify_recommendation("moderate", 0.25, 4.0, is_padded=False, avg_age_days=None)
    assert result in ("monitor", "validate_further")


# ── _classify_opportunity_type ────────────────────────────────────────────────

@pytest.mark.parametrize("cat, expected", [
    ("Operational efficiency", "operational"),
    ("Cost reduction", "operational"),
    ("Risk mitigation", "compliance"),
    ("Regulatory & permits", "compliance"),
    ("Market entry", "strategic"),
    ("Growth and scale", "strategic"),
    ("Partnership and M&A", "strategic"),
])
def test_opportunity_type_mapping(cat, expected):
    assert _classify_opportunity_type(cat) == expected


def test_opportunity_type_unknown_defaults_operational():
    assert _classify_opportunity_type("Unknown category") == "operational"


# ── _build_problem_specific_commercial_angle ──────────────────────────────────

def test_commercial_angle_labor_keyword():
    angle = _build_problem_specific_commercial_angle("Labor shortages driving up wages", "Operational efficiency")
    assert "workforce" in angle.lower() or "staffing" in angle.lower() or "labor" in angle.lower()


def test_commercial_angle_permit_keyword():
    angle = _build_problem_specific_commercial_angle("Permitting and regulatory delays", "Regulatory & permits")
    assert "permit" in angle.lower() or "compliance" in angle.lower()


def test_commercial_angle_supply_chain():
    angle = _build_problem_specific_commercial_angle("Supply chain disruptions and logistics gaps", "Operational efficiency")
    assert "supply chain" in angle.lower() or "procurement" in angle.lower()


def test_commercial_angle_cost_keyword():
    angle = _build_problem_specific_commercial_angle("Inflation and cost escalation pressures", "Cost reduction")
    assert "cost" in angle.lower() or "financial" in angle.lower() or "procurement" in angle.lower()


def test_commercial_angle_security_keyword():
    angle = _build_problem_specific_commercial_angle("Cybersecurity risk exposure", "Risk mitigation")
    assert "cyber" in angle.lower() or "security" in angle.lower()


def test_commercial_angle_fallback_to_category():
    # Problem with no known keyword → falls back to category map
    angle = _build_problem_specific_commercial_angle("General market challenges", "Partnership and M&A")
    assert len(angle) > 10  # not empty


def test_commercial_angle_differs_across_problems():
    a1 = _build_problem_specific_commercial_angle("Labor shortages", "Operational efficiency")
    a2 = _build_problem_specific_commercial_angle("Permitting delays", "Operational efficiency")
    assert a1 != a2


# ── _build_opportunity_brief: quality-aware suggested_next_step ───────────────

def test_brief_weak_support_overrides_pain_score():
    """Weak support → validate signal quality, regardless of high pain score."""
    ev = _mixed_evidence(2, 2)
    brief = _build_opportunity_brief(
        title="Labor shortages",
        ai_category="Operational efficiency",
        pain_score=9.0,  # would normally → "Initiate direct outreach"
        evidence=ev,
        industry="Construction",
        support_level="weak",
    )
    assert "validate" in brief.suggested_next_step.lower()
    assert "thin" in brief.suggested_next_step.lower() or "stale" in brief.suggested_next_step.lower()


def test_brief_strong_support_high_pain_no_weak_override():
    """Strong support + high pain → pursue_now next step (not validate)."""
    ev = _mixed_evidence(2, 2)
    brief = _build_opportunity_brief(
        title="Labor shortages",
        ai_category="Operational efficiency",
        pain_score=9.0,
        evidence=ev,
        industry="Construction",
        support_level="strong",
    )
    assert "validate signal quality" not in brief.suggested_next_step.lower()
    assert "outreach" in brief.suggested_next_step.lower()


def test_brief_moderate_support_follows_pain_ladder():
    ev = _evidence(2)
    brief = _build_opportunity_brief(
        title="Supply chain delays",
        ai_category="Operational efficiency",
        pain_score=5.0,  # → "Run a second data collection pass"
        evidence=ev,
        industry="Manufacturing",
        support_level="moderate",
    )
    assert "data collection" in brief.suggested_next_step.lower() or "monitor" in brief.suggested_next_step.lower()


def test_brief_commercial_angle_is_problem_specific():
    """Brief commercial_angle should reflect the problem keywords, not just the category."""
    ev = _evidence(2)
    brief_labor = _build_opportunity_brief(
        title="Labor shortages and wage pressure",
        ai_category="Operational efficiency",
        pain_score=6.0,
        evidence=ev,
        industry="Construction",
    )
    brief_permit = _build_opportunity_brief(
        title="Permitting and regulatory delays",
        ai_category="Operational efficiency",
        pain_score=6.0,
        evidence=ev,
        industry="Construction",
    )
    assert brief_labor.commercial_angle != brief_permit.commercial_angle


# ── New fields present in strategy output ────────────────────────────────────

def _make_minimal_strategy() -> StrategyOutput:
    """Build a minimal StrategyOutput with required fields for field presence tests."""
    from marketscout.brain.schema import (
        BusinessCase, DataQuality, EvidenceItem, OpportunityItem,
        ScoreBreakdown, SignalsUsed, StrategyOutput,
    )
    opp = OpportunityItem(
        title="Labor shortages",
        problem="Labor shortages and wage pressure",
        ai_category="Operational efficiency",
        evidence=[EvidenceItem(title="h", link="http://x.com", source="headline")],
        pain_score=6.0,
        automation_potential=5.0,
        roi_signal=5.0,
        confidence=0.5,
        business_case=BusinessCase(savings_range_annual="$50k–$200k"),
        score_breakdown=ScoreBreakdown(signal_frequency=0.5, source_diversity=0.3, job_role_density=0.2),
        trend_key="operational_efficiency::labor_shortages_and_wage_pressure",
        recommendation="validate_further",
        opportunity_type="operational",
    )
    return StrategyOutput(
        city="Vancouver",
        industry="Construction",
        opportunity_map=[opp] * 5,
        signals_used=SignalsUsed(headlines_count=5, jobs_count=3),
        data_quality=DataQuality(freshness_window_days=7, coverage_score=0.7, source_mix_score=0.6),
    )


def test_strategy_output_has_trend_key():
    strategy = _make_minimal_strategy()
    for opp in strategy.opportunity_map:
        assert hasattr(opp, "trend_key")
        assert isinstance(opp.trend_key, str)


def test_strategy_output_has_recommendation():
    strategy = _make_minimal_strategy()
    for opp in strategy.opportunity_map:
        assert opp.recommendation in ("pursue_now", "monitor", "validate_further", "deprioritize")


def test_strategy_output_has_opportunity_type():
    strategy = _make_minimal_strategy()
    for opp in strategy.opportunity_map:
        assert opp.opportunity_type in ("operational", "strategic", "compliance")


def test_strategy_json_roundtrip_preserves_new_fields():
    strategy = _make_minimal_strategy()
    d = strategy.to_json_dict()
    restored = StrategyOutput.model_validate(d)
    opp = restored.opportunity_map[0]
    assert opp.trend_key == "operational_efficiency::labor_shortages_and_wage_pressure"
    assert opp.recommendation == "validate_further"
    assert opp.opportunity_type == "operational"


# ── DB persistence of trend_key and recommendation ──────────────────────────

def _db_conn():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    return get_connection(Path(tmp.name))


def _make_run_strategy(trend_key: str = "ops::labor", recommendation: str = "validate_further"):
    """Build a minimal StrategyOutput for DB save tests."""
    from marketscout.brain.schema import (
        BusinessCase, DataQuality, EvidenceItem, OpportunityItem,
        ScoreBreakdown, SignalsUsed, StrategyOutput,
    )
    opp = OpportunityItem(
        title="Labor shortages",
        problem="Labor shortages",
        ai_category="Operational efficiency",
        evidence=[EvidenceItem(title="h", link="http://x.com/1", source="headline")],
        pain_score=6.0,
        automation_potential=5.0,
        roi_signal=5.0,
        confidence=0.5,
        business_case=BusinessCase(savings_range_annual="$50k–$200k"),
        score_breakdown=ScoreBreakdown(signal_frequency=0.5, source_diversity=0.3, job_role_density=0.2),
        trend_key=trend_key,
        recommendation=recommendation,
        opportunity_type="operational",
    )
    # Pad to 5
    padded_opps = [opp] + [
        OpportunityItem(
            title=f"Pad {i}",
            problem=f"Pad {i}",
            ai_category="Operational efficiency",
            evidence=[EvidenceItem(title="p", link=f"http://x.com/p{i}", source="headline")],
            pain_score=3.0,
            automation_potential=5.0,
            roi_signal=4.0,
            confidence=0.3,
            business_case=BusinessCase(savings_range_annual="$30k–$100k"),
            score_breakdown=ScoreBreakdown(signal_frequency=1/3, source_diversity=1/3, job_role_density=1/3),
            trend_key=f"padded::pad_{i}",
            recommendation="deprioritize",
            opportunity_type="operational",
            is_padded=True,
            support_level="weak",
        )
        for i in range(4)
    ]
    return StrategyOutput(
        city="Vancouver",
        industry="Construction",
        opportunity_map=padded_opps,
        signals_used=SignalsUsed(headlines_count=5, jobs_count=3),
        data_quality=DataQuality(freshness_window_days=7, coverage_score=0.7, source_mix_score=0.6),
    )


def test_db_persists_trend_key():
    conn = _db_conn()
    strategy = _make_run_strategy(trend_key="ops::labor_shortages")
    save_run(
        conn, "run1", "Vancouver", "Construction", strategy,
        [], [], {"headlines": {}, "jobs": {}},
        {"started_at_iso": "2024-01-01T00:00:00Z", "deterministic": False},
        "deterministic",
    )
    row = conn.execute("SELECT trend_key FROM opportunities WHERE title = 'Labor shortages'").fetchone()
    assert row is not None
    assert row["trend_key"] == "ops::labor_shortages"


def test_db_persists_recommendation():
    conn = _db_conn()
    strategy = _make_run_strategy(recommendation="pursue_now")
    save_run(
        conn, "run2", "Vancouver", "Construction", strategy,
        [], [], {"headlines": {}, "jobs": {}},
        {"started_at_iso": "2024-01-01T00:00:00Z", "deterministic": False},
        "deterministic",
    )
    row = conn.execute("SELECT recommendation FROM opportunities WHERE title = 'Labor shortages'").fetchone()
    assert row is not None
    assert row["recommendation"] == "pursue_now"


def test_db_compare_runs_includes_trend_key():
    conn = _db_conn()
    strategy = _make_run_strategy(trend_key="ops::labor_shortages")
    for i, rid in enumerate(["r1", "r2"]):
        save_run(
            conn, rid, "Toronto", "Retail", strategy,
            [], [], {"headlines": {}, "jobs": {}},
            {"started_at_iso": f"2024-0{i+1}-01T00:00:00Z", "deterministic": False},
            "deterministic",
        )
    _, opp_rows = compare_runs(conn, "Toronto", "Retail", limit_runs=3)
    labor_row = next((r for r in opp_rows if r["title"] == "Labor shortages"), None)
    assert labor_row is not None
    assert labor_row["trend_key"] == "ops::labor_shortages"
