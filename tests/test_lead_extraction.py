"""Tests for Phase 5: Per-opportunity lead extraction.

Covers:
  - _extract_company_from_headline: regex patterns
  - _build_leads_for_opportunity: job matching, news matching, dedup, ranking, empty cases
  - Lead model validation (schema)
  - Determinism
  - Integration: all opportunities in strategy output have leads field
  - JSON roundtrip preserves leads
  - DB persistence of leads
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from marketscout.brain.strategy import (
    _build_leads_for_opportunity,
    _extract_company_from_headline,
    generate_mock_strategy,
)
from marketscout.brain.schema import EvidenceItem, Lead, StrategyOutput
from marketscout.db import get_connection, save_run


# ── Helpers ────────────────────────────────────────────────────────────────────

def _ev(title: str, link: str, source: str = "headline") -> EvidenceItem:
    return EvidenceItem(title=title, link=link, source=source)


def _leads(
    problem: str = "Labor shortages and wage pressure",
    keywords: set[str] | None = None,
    headlines: list[dict] | None = None,
    jobs: list[dict] | None = None,
    evidence: list[EvidenceItem] | None = None,
) -> list[Lead]:
    return _build_leads_for_opportunity(
        problem=problem,
        keywords=keywords if keywords is not None else {"labor"},
        headlines=headlines or [],
        jobs=jobs or [],
        evidence=evidence or [],
    )


# ── _extract_company_from_headline ─────────────────────────────────────────────

def test_extract_company_corp_suffix():
    result = _extract_company_from_headline("Acme Corp announces new hiring drive")
    assert result == "Acme Corp"


def test_extract_company_inc_suffix():
    result = _extract_company_from_headline("Pacific Coast Construction Inc. wins contract")
    assert result is not None
    assert "Pacific" in result


def test_extract_company_group_suffix():
    result = _extract_company_from_headline("BuildRight Group reports labor shortages")
    assert result == "BuildRight Group"


def test_extract_company_services_suffix():
    result = _extract_company_from_headline("Metro Staffing Services struggles to fill roles")
    assert result is not None
    assert "Metro" in result


def test_extract_company_no_match_returns_none():
    result = _extract_company_from_headline("Labor shortages hit construction sector")
    assert result is None


def test_extract_company_no_match_lowercase():
    result = _extract_company_from_headline("some company inc does stuff")
    assert result is None  # no uppercase leading word


# ── _build_leads_for_opportunity — basic job matching ─────────────────────────

def test_job_match_returns_lead():
    jobs = [{"title": "Labor Coordinator", "company": "BuildCo", "link": "https://j.com/1", "published": ""}]
    result = _leads(keywords={"labor"}, jobs=jobs)
    assert len(result) == 1
    assert result[0].company_name == "BuildCo"
    assert result[0].signal_type == "job"


def test_job_no_match_skipped():
    jobs = [{"title": "Marketing Manager", "company": "MktCo", "link": "https://j.com/2", "published": ""}]
    result = _leads(keywords={"labor"}, jobs=jobs)
    assert result == []


def test_job_empty_company_skipped():
    jobs = [{"title": "Labor Coordinator", "company": "", "link": "https://j.com/3", "published": ""}]
    result = _leads(keywords={"labor"}, jobs=jobs)
    assert result == []


def test_job_lead_reason_contains_job_title():
    jobs = [{"title": "Labor Coordinator", "company": "BuildCo", "link": "https://j.com/4", "published": ""}]
    result = _leads(keywords={"labor"}, jobs=jobs)
    assert "Labor Coordinator" in result[0].reason


# ── _build_leads_for_opportunity — news headline matching ──────────────────────

def test_headline_with_corp_suffix_extracted():
    headlines = [{"title": "Acme Corp facing labor shortage crisis", "link": "https://h.com/1", "published": ""}]
    result = _leads(keywords={"labor"}, headlines=headlines)
    assert len(result) == 1
    assert result[0].company_name == "Acme Corp"
    assert result[0].signal_type == "news"


def test_headline_no_corp_suffix_no_lead():
    headlines = [{"title": "Labor shortage hits Vancouver industry", "link": "https://h.com/2", "published": ""}]
    result = _leads(keywords={"labor"}, headlines=headlines)
    assert result == []


def test_headline_keyword_mismatch_no_lead():
    headlines = [{"title": "Metro Corp lands new contract", "link": "https://h.com/3", "published": ""}]
    result = _leads(keywords={"labor"}, headlines=headlines)
    assert result == []


# ── Scoring and ranking ────────────────────────────────────────────────────────

def test_job_scores_higher_than_news():
    """Job signal (2.0) should outrank news signal (1.0) for different companies."""
    jobs = [{"title": "Labor Manager", "company": "JobCo", "link": "https://j.com/10", "published": ""}]
    headlines = [{"title": "Metro Services reporting labor shortages", "link": "https://h.com/10", "published": ""}]
    result = _leads(keywords={"labor"}, jobs=jobs, headlines=headlines)
    companies = [r.company_name for r in result]
    assert "JobCo" in companies
    assert "Metro Services" in companies
    assert companies.index("JobCo") < companies.index("Metro Services")


def test_evidence_match_gives_bonus():
    """Company in evidence gets +1.0 bonus score."""
    ev = [_ev("Labor Coordinator", "https://j.com/ev1", "job")]
    jobs_a = [{"title": "Labor Coordinator", "company": "EvidenceCo", "link": "https://j.com/ev1", "published": ""}]
    jobs_b = [{"title": "Labor Analyst", "company": "OtherCo", "link": "https://j.com/other", "published": ""}]
    result = _leads(keywords={"labor"}, jobs=jobs_a + jobs_b, evidence=ev)
    assert result[0].company_name == "EvidenceCo"
    assert result[0].priority_score == pytest.approx(3.0)


def test_frequency_bonus_accumulates():
    """Same company appearing in multiple matching signals gets frequency bonus."""
    jobs = [
        {"title": "Labor Coordinator", "company": "BigCo", "link": "https://j.com/a", "published": ""},
        {"title": "Labor Manager", "company": "BigCo", "link": "https://j.com/b", "published": ""},
        {"title": "Labor Analyst", "company": "SmallCo", "link": "https://j.com/c", "published": ""},
    ]
    result = _leads(keywords={"labor"}, jobs=jobs)
    bigco = next(r for r in result if r.company_name == "BigCo")
    smallco = next(r for r in result if r.company_name == "SmallCo")
    assert bigco.priority_score > smallco.priority_score


def test_top_5_max_leads():
    """Never more than 5 leads per opportunity."""
    jobs = [
        {"title": "Labor Coordinator", "company": f"Co{i}", "link": f"https://j.com/{i}", "published": ""}
        for i in range(10)
    ]
    result = _leads(keywords={"labor"}, jobs=jobs)
    assert len(result) <= 5


# ── Deduplication ─────────────────────────────────────────────────────────────

def test_dedup_same_company_from_multiple_signals():
    """Same company appearing in two jobs → one lead with frequency bonus."""
    jobs = [
        {"title": "Labor Coordinator", "company": "BuildCo", "link": "https://j.com/1", "published": ""},
        {"title": "Labor Manager", "company": "BuildCo", "link": "https://j.com/2", "published": ""},
    ]
    result = _leads(keywords={"labor"}, jobs=jobs)
    companies = [r.company_name for r in result]
    assert companies.count("BuildCo") == 1


def test_dedup_case_insensitive():
    """'buildco' and 'BuildCo' should dedup to one entry."""
    jobs = [
        {"title": "Labor Coordinator", "company": "BuildCo", "link": "https://j.com/1", "published": ""},
        {"title": "Labor Manager", "company": "buildco", "link": "https://j.com/2", "published": ""},
    ]
    result = _leads(keywords={"labor"}, jobs=jobs)
    assert len(result) == 1


# ── Empty / edge cases ────────────────────────────────────────────────────────

def test_no_signals_returns_empty():
    result = _leads(keywords={"labor"}, headlines=[], jobs=[])
    assert result == []


def test_empty_keywords_uses_problem_words():
    """With no keywords, problem words (≥4 chars) serve as search terms."""
    jobs = [{"title": "Labor Coordinator", "company": "BuildCo", "link": "https://j.com/1", "published": ""}]
    result = _leads(
        problem="Labor shortages and wage pressure",
        keywords=set(),
        jobs=jobs,
    )
    # "labor", "shortages", "wage", "pressure" should match "Labor Coordinator"
    assert any(r.company_name == "BuildCo" for r in result)


def test_all_keywords_no_match_returns_empty():
    jobs = [{"title": "Marketing Director", "company": "MktCo", "link": "https://j.com/1", "published": ""}]
    result = _leads(keywords={"labor", "shortage"}, jobs=jobs)
    assert result == []


# ── Determinism ───────────────────────────────────────────────────────────────

def test_leads_are_deterministic():
    jobs = [
        {"title": "Labor Coordinator", "company": f"Co{i}", "link": f"https://j.com/{i}", "published": ""}
        for i in range(7)
    ]
    r1 = _leads(keywords={"labor"}, jobs=jobs)
    r2 = _leads(keywords={"labor"}, jobs=jobs)
    assert [l.company_name for l in r1] == [l.company_name for l in r2]


# ── Lead model validation ─────────────────────────────────────────────────────

def test_lead_model_fields():
    lead = Lead(
        company_name="BuildCo",
        reason="Hiring for Labor Coordinator",
        signal_type="job",
        signal_reference="Labor Coordinator",
        priority_score=2.5,
    )
    assert lead.company_name == "BuildCo"
    assert lead.signal_type == "job"
    assert 0.0 <= lead.priority_score <= 10.0


def test_lead_priority_score_bounds():
    with pytest.raises(Exception):
        Lead(
            company_name="Co",
            reason="r",
            signal_type="job",
            signal_reference="ref",
            priority_score=11.0,
        )


# ── Integration: strategy output ──────────────────────────────────────────────

def test_all_strategy_opportunities_have_leads_field():
    """Every OpportunityItem must have a leads field (may be empty list)."""
    strategy = generate_mock_strategy(
        [{"title": "Labor shortage hits Vancouver", "link": "https://h.com/1", "source": "A", "published": ""}],
        "Construction", "Vancouver",
        jobs=[{"title": "Labor Coordinator", "company": "BuildCo", "link": "https://j.com/1", "published": "", "source": ""}],
    )
    for opp in strategy.opportunity_map:
        assert hasattr(opp, "leads")
        assert isinstance(opp.leads, list)
        for lead in opp.leads:
            assert isinstance(lead, Lead)
            assert lead.company_name.strip()
            assert lead.signal_type in ("job", "news")
            assert 0.0 <= lead.priority_score <= 10.0


def test_strategy_with_jobs_produces_job_leads():
    """When jobs have matching keywords, at least one opportunity should have job leads."""
    jobs = [
        {"title": "Labor Coordinator", "company": "BuildCo", "link": "https://j.com/1", "published": "", "source": ""},
        {"title": "Labor Manager", "company": "AnotherCo", "link": "https://j.com/2", "published": "", "source": ""},
    ]
    headlines = [{"title": "Labor shortage hits industry", "link": "https://h.com/1", "source": "A", "published": ""}]
    strategy = generate_mock_strategy(headlines, "Construction", "Vancouver", jobs=jobs)
    all_leads = [lead for opp in strategy.opportunity_map for lead in opp.leads]
    job_leads = [ld for ld in all_leads if ld.signal_type == "job"]
    assert job_leads, "Expected at least one job-sourced lead across all opportunities"


def test_strategy_no_signals_leads_are_empty():
    """With no matching signals, leads will be empty lists."""
    strategy = generate_mock_strategy([], "Construction", "Vancouver")
    for opp in strategy.opportunity_map:
        assert opp.leads == []


# ── JSON roundtrip ────────────────────────────────────────────────────────────

def test_leads_json_roundtrip():
    jobs = [{"title": "Labor Coordinator", "company": "BuildCo", "link": "https://j.com/1", "published": "", "source": ""}]
    headlines = [{"title": "Labor shortage hits Vancouver", "link": "https://h.com/1", "source": "A", "published": ""}]
    strategy = generate_mock_strategy(headlines, "Construction", "Vancouver", jobs=jobs)
    d = strategy.to_json_dict()
    restored = StrategyOutput.model_validate(d)
    for orig, rest in zip(strategy.opportunity_map, restored.opportunity_map):
        orig_names = [ld.company_name for ld in orig.leads]
        rest_names = [ld.company_name for ld in rest.leads]
        assert orig_names == rest_names


# ── DB persistence ────────────────────────────────────────────────────────────

def _make_strategy_with_leads():
    from marketscout.brain.schema import (
        BusinessCase, DataQuality, EvidenceItem, Lead, OpportunityItem,
        ScoreBreakdown, SignalsUsed, StrategyOutput,
    )
    opp = OpportunityItem(
        title="Labor shortages",
        problem="Labor shortages and wage pressure",
        ai_category="Operational efficiency",
        evidence=[EvidenceItem(title="h", link="http://x.com/1", source="headline")],
        pain_score=7.0,
        automation_potential=5.0,
        roi_signal=5.0,
        confidence=0.6,
        business_case=BusinessCase(savings_range_annual="$50k–$200k"),
        score_breakdown=ScoreBreakdown(signal_frequency=0.5, source_diversity=0.3, job_role_density=0.2),
        trend_key="ops::labor",
        recommendation="pursue_now",
        opportunity_type="operational",
        suggested_actions=["Pull top companies from leads.csv"],
        leads=[
            Lead(
                company_name="BuildCo",
                reason="Hiring for Labor Coordinator",
                signal_type="job",
                signal_reference="Labor Coordinator",
                priority_score=3.0,
            ),
            Lead(
                company_name="AnotherCo",
                reason="Hiring for Labor Manager",
                signal_type="job",
                signal_reference="Labor Manager",
                priority_score=2.0,
            ),
        ],
    )
    padded = [
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
            suggested_actions=["Do not invest resources yet — signal quality is insufficient to justify action"],
        )
        for i in range(4)
    ]
    return StrategyOutput(
        city="Vancouver",
        industry="Construction",
        opportunity_map=[opp] + padded,
        signals_used=SignalsUsed(headlines_count=3, jobs_count=2),
        data_quality=DataQuality(freshness_window_days=7, coverage_score=0.7, source_mix_score=0.6),
    )


def test_db_persists_leads():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    conn = get_connection(Path(tmp.name))
    strategy = _make_strategy_with_leads()
    save_run(
        conn, "leads-run-1", "Vancouver", "Construction", strategy,
        [], [], {"headlines": {}, "jobs": {}},
        {"started_at_iso": "2024-01-01T00:00:00Z", "deterministic": False},
        "deterministic",
    )
    row = conn.execute(
        "SELECT leads FROM opportunities WHERE title = 'Labor shortages'"
    ).fetchone()
    assert row is not None
    stored = json.loads(row["leads"])
    assert isinstance(stored, list)
    assert len(stored) == 2
    assert stored[0]["company_name"] == "BuildCo"
    assert stored[0]["signal_type"] == "job"
    assert stored[0]["priority_score"] == pytest.approx(3.0)


def test_db_leads_roundtrip_preserves_all_fields():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    conn = get_connection(Path(tmp.name))
    strategy = _make_strategy_with_leads()
    save_run(
        conn, "leads-run-2", "Vancouver", "Construction", strategy,
        [], [], {"headlines": {}, "jobs": {}},
        {"started_at_iso": "2024-01-01T00:00:00Z", "deterministic": False},
        "deterministic",
    )
    row = conn.execute(
        "SELECT leads FROM opportunities WHERE title = 'Labor shortages'"
    ).fetchone()
    stored = json.loads(row["leads"])
    expected = [ld.model_dump() for ld in strategy.opportunity_map[0].leads]
    assert stored == expected
