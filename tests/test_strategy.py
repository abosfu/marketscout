"""Strategy generation, schema validation, report rendering, and leads builder tests."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from marketscout.backend.ai.report_html import strategy_to_html
from marketscout.backend.ai.report_md import strategy_to_markdown
from marketscout.backend.schema import (
    AI_CATEGORIES,
    BusinessCase,
    DataQuality,
    EvidenceItem,
    OpportunityBrief,
    OpportunityItem,
    SignalsUsed,
    StrategyOutput,
    get_json_schema,
)
from marketscout.backend.ai.strategy import _build_opportunity_brief, generate_mock_strategy, generate_strategy
from marketscout.leads import LeadRow, build_leads


# ── Strategy generation ───────────────────────────────────────────────────────

def test_generate_mock_strategy_returns_v2_schema() -> None:
    """Mock strategy generator produces a valid v2.0 StrategyOutput with 5–8 opportunities."""
    headlines = [
        {"title": "Labor shortage in Vancouver", "link": "https://a.com", "source": "A"},
        {"title": "Housing crisis and rates", "link": "https://b.com", "source": "B"},
        {"title": "Supply chain issues", "link": "https://c.com", "source": "C"},
    ]
    strategy = generate_mock_strategy(headlines, industry="Construction", city="Vancouver")
    assert isinstance(strategy, StrategyOutput)
    assert strategy.strategy_version == "2.0"
    assert strategy.city == "Vancouver" and strategy.industry == "Construction"
    assert 5 <= len(strategy.opportunity_map) <= 8
    assert strategy.signals_used.headlines_count == 3
    assert strategy.signals_used.jobs_count == 0
    assert 0 <= strategy.data_quality.coverage_score <= 1
    assert 0 <= strategy.data_quality.source_mix_score <= 1
    for o in strategy.opportunity_map:
        assert 0 <= o.pain_score <= 10
        assert 0 <= o.roi_signal <= 10
        assert 0 <= o.confidence <= 1
        assert len(o.evidence) >= 1
        sb = getattr(o, "score_breakdown", None)
        if sb is not None:
            total = sb.signal_frequency + sb.source_diversity + sb.job_role_density
            assert abs(total - 1.0) < 1e-6, f"score_breakdown should sum to 1.0, got {total}"


def test_generate_mock_strategy_works_with_empty_headlines() -> None:
    """Mock strategy with no headlines still produces 5–8 opportunities via fallback templates."""
    strategy = generate_mock_strategy([], industry="Technology", city="Vancouver")
    assert isinstance(strategy, StrategyOutput)
    assert strategy.strategy_version == "2.0"
    assert 5 <= len(strategy.opportunity_map) <= 8


def test_generate_strategy_force_mock_returns_v2() -> None:
    """generate_strategy(force_mock=True) returns a v2.0 StrategyOutput."""
    strategy = generate_strategy(
        [{"title": "Test", "link": "#", "source": ""}],
        industry="Retail",
        city="Toronto",
        force_mock=True,
    )
    assert isinstance(strategy, StrategyOutput)
    assert strategy.strategy_version == "2.0"
    assert 5 <= len(strategy.opportunity_map) <= 8
    assert strategy.city == "Toronto" and strategy.industry == "Retail"


def test_evidence_links_from_inputs_only() -> None:
    """All evidence links in opportunity_map exist in the provided headlines/jobs (no hallucination)."""
    headlines = [
        {"title": "Labor shortage", "link": "https://example.com/h1", "source": "S1"},
        {"title": "Rate hike", "link": "https://example.com/h2", "source": "S2"},
    ]
    jobs = [
        {"title": "Construction Coordinator", "company": "Co", "link": "https://example.com/j1", "published": "", "source": ""},
    ]
    strategy = generate_mock_strategy(headlines, industry="Construction", city="Vancouver", jobs=jobs)
    allowed_links = {h.get("link") for h in headlines} | {j.get("link") for j in jobs}
    allowed_links.add("#")
    for o in strategy.opportunity_map:
        for e in o.evidence:
            assert e.link in allowed_links, f"Evidence link {e.link!r} not in input signals"
            assert e.title


def test_score_breakdown_exists_and_sums_to_one() -> None:
    """Every opportunity has score_breakdown; components sum to 1.0."""
    headlines = [
        {"title": "Labor shortage", "link": "https://a.com", "source": "A"},
        {"title": "Rate hike", "link": "https://b.com", "source": "B"},
    ]
    jobs = [{"title": "Construction job", "company": "C", "link": "https://c.com", "published": "", "source": ""}]
    strategy = generate_mock_strategy(headlines, industry="Construction", city="Vancouver", jobs=jobs)
    for o in strategy.opportunity_map:
        assert o.score_breakdown is not None
        sb = o.score_breakdown
        total = sb.signal_frequency + sb.source_diversity + sb.job_role_density
        assert abs(total - 1.0) < 1e-6, f"score_breakdown sum {total} != 1.0"


def test_deterministic_mode_produces_identical_outputs() -> None:
    """deterministic=True: two runs with identical inputs produce identical opportunity maps."""
    headlines = [
        {"title": "Labor shortage in Vancouver", "link": "https://a.com", "source": "A"},
        {"title": "Housing and rates", "link": "https://b.com", "source": "B"},
        {"title": "Supply chain delays", "link": "https://c.com", "source": "C"},
    ]
    jobs = [
        {"title": "Construction Coordinator", "company": "Co", "link": "https://j.com", "published": "", "source": ""},
    ]
    s1 = generate_mock_strategy(headlines, industry="Construction", city="Vancouver", jobs=jobs, deterministic=True)
    s2 = generate_mock_strategy(headlines, industry="Construction", city="Vancouver", jobs=jobs, deterministic=True)
    assert len(s1.opportunity_map) == len(s2.opportunity_map)
    for i, (o1, o2) in enumerate(zip(s1.opportunity_map, s2.opportunity_map)):
        assert o1.problem == o2.problem, f"Opportunity {i} problem mismatch"
        assert o1.pain_score == o2.pain_score, f"Opportunity {i} pain_score mismatch"
        assert o1.confidence == o2.confidence, f"Opportunity {i} confidence mismatch"
        assert o1.roi_signal == o2.roi_signal, f"Opportunity {i} roi_signal mismatch"
    assert s1.to_json_dict()["opportunity_map"] == s2.to_json_dict()["opportunity_map"]


# ── Schema validation ─────────────────────────────────────────────────────────

def test_v2_fixture_validates_schema_and_scores(sample_strategy_v2_path: Path) -> None:
    """V2.0 fixture validates against StrategyOutput; all scores are within bounds."""
    data = json.loads(sample_strategy_v2_path.read_text())
    strategy = StrategyOutput.model_validate(data)
    assert strategy.strategy_version == "2.0"
    assert strategy.city == "Vancouver" and strategy.industry == "Construction"
    assert 5 <= len(strategy.opportunity_map) <= 8
    assert strategy.signals_used.headlines_count >= 0
    assert 0 <= strategy.data_quality.coverage_score <= 1
    assert 0 <= strategy.data_quality.source_mix_score <= 1
    for o in strategy.opportunity_map:
        assert o.ai_category in AI_CATEGORIES
        assert 0 <= o.pain_score <= 10
        assert 0 <= o.automation_potential <= 10
        assert 0 <= o.roi_signal <= 10
        assert 0 <= o.confidence <= 1
        assert len(o.evidence) >= 1


def test_opportunity_map_length_bounds() -> None:
    """StrategyOutput rejects opportunity_map with fewer than 5 or more than 8 items."""
    def make_opp(i: int) -> dict:
        return {
            "title": f"Opp {i}", "problem": f"Problem {i}",
            "ai_category": "Operational efficiency",
            "evidence": [{"title": "E", "link": "https://x.com", "source": "headline"}],
            "pain_score": 5.0, "automation_potential": 5.0, "roi_signal": 5.0, "confidence": 0.5,
            "business_case": {"savings_range_annual": "$50k", "assumptions": []},
        }
    base = {
        "strategy_version": "2.0", "city": "Vancouver", "industry": "Construction",
        "signals_used": {"headlines_count": 5, "jobs_count": 0, "news_sources_count": 2, "job_companies_count": 0},
        "data_quality": {"freshness_window_days": 1, "coverage_score": 0.5, "source_mix_score": 0.5},
    }
    StrategyOutput.model_validate({**base, "opportunity_map": [make_opp(i) for i in range(5)]})
    StrategyOutput.model_validate({**base, "opportunity_map": [make_opp(i) for i in range(8)]})
    with pytest.raises(ValidationError):
        StrategyOutput.model_validate({**base, "opportunity_map": [make_opp(i) for i in range(4)]})
    with pytest.raises(ValidationError):
        StrategyOutput.model_validate({**base, "opportunity_map": [make_opp(i) for i in range(9)]})


def test_get_json_schema_returns_dict() -> None:
    """get_json_schema returns a JSON-serialisable schema dict."""
    schema = get_json_schema()
    assert isinstance(schema, dict)
    assert "properties" in schema or "title" in schema
    json.dumps(schema)


# ── Markdown report ───────────────────────────────────────────────────────────

def test_markdown_report_renders_opportunity_map(sample_strategy_v2_path: Path) -> None:
    """Markdown report is non-empty and contains Opportunity Map with at least 5 items."""
    data = json.loads(sample_strategy_v2_path.read_text())
    md = strategy_to_markdown(data)
    assert md and md.strip()
    assert "Opportunity Map" in md
    assert "| Title |" in md or "| Pain |" in md
    strategy = StrategyOutput.model_validate(data)
    for o in strategy.opportunity_map[:5]:
        assert o.title[:20] in md or o.problem[:20] in md


def test_markdown_report_accepts_strategy_output_object() -> None:
    """Report generator accepts a StrategyOutput instance (not just a dict)."""
    strategy = StrategyOutput(
        strategy_version="2.0",
        city="Vancouver",
        industry="Construction",
        opportunity_map=[
            OpportunityItem(
                title="Opp 1", problem="Problem 1",
                ai_category="Operational efficiency",
                evidence=[EvidenceItem(title="E1", link="https://x.com", source="headline")],
                pain_score=5.0, automation_potential=5.0, roi_signal=5.0, confidence=0.5,
                business_case=BusinessCase(savings_range_annual="$50k", assumptions=[]),
            )
        ] * 5,
        signals_used=SignalsUsed(headlines_count=5, jobs_count=0, news_sources_count=2, job_companies_count=0),
        data_quality=DataQuality(freshness_window_days=1, coverage_score=0.5, source_mix_score=0.5),
    )
    md = strategy_to_markdown(strategy)
    assert "Executive Summary" in md
    assert "Opportunity Map" in md
    assert "Sources" in md
    assert "Vancouver" in md and "Construction" in md


def test_markdown_report_includes_data_quality_section(sample_strategy_v2_path: Path) -> None:
    """Markdown report includes a data quality or signals section."""
    data = json.loads(sample_strategy_v2_path.read_text())
    md = strategy_to_markdown(data)
    assert "Data quality" in md or "Signals" in md or "headlines" in md


def test_markdown_report_safe_on_invalid_input() -> None:
    """Report returns a safe fallback string rather than raising on invalid data."""
    md = strategy_to_markdown({})
    assert "Strategy Report" in md or "Unable to validate" in md


# ── HTML report ───────────────────────────────────────────────────────────────

def test_html_report_renders_opportunity_map(sample_strategy_v2_path: Path) -> None:
    """HTML report is non-empty, contains valid HTML, and includes Opportunity Map."""
    data = json.loads(sample_strategy_v2_path.read_text())
    html = strategy_to_html(data)
    assert html and html.strip()
    assert "<!DOCTYPE html>" in html or "<html" in html
    assert "Opportunity Map" in html
    strategy = StrategyOutput.model_validate(data)
    for o in strategy.opportunity_map[:5]:
        assert o.title[:30] in html or o.problem[:30] in html


def test_html_report_safe_on_invalid_input() -> None:
    """HTML report returns a safe fallback rather than raising on invalid data."""
    html = strategy_to_html({})
    assert "Strategy Report" in html or "Unable to validate" in html
    assert "<" in html and ">" in html


# ── Leads builder ─────────────────────────────────────────────────────────────

def test_build_leads_groups_by_company_and_scores() -> None:
    """build_leads aggregates jobs per company and computes readiness_score correctly."""
    jobs = [
        {"title": "Scheduling Coordinator", "company": "Contoso Construction",
         "location": "Vancouver, BC", "link": "https://example.com/job-1",
         "published": "2025-02-24T10:00:00Z", "source": "adzuna"},
        {"title": "Construction Assistant", "company": "Contoso Construction",
         "location": "Vancouver, BC", "link": "https://example.com/job-2",
         "published": "2025-02-24T11:00:00Z", "source": "adzuna"},
        {"title": "Project Manager", "company": "OtherCo",
         "location": "Vancouver, BC", "link": "https://example.com/job-3",
         "published": "2025-02-24T12:00:00Z", "source": "adzuna"},
    ]
    leads = build_leads(jobs)
    assert isinstance(leads, list)
    assert all(isinstance(l, LeadRow) for l in leads)
    top = leads[0]
    assert top.company == "Contoso Construction"
    assert top.job_count == 2
    assert top.top_keywords.startswith("coordinator")
    assert "assistant" in top.top_keywords
    assert top.readiness_score == 50
    assert "https://example.com/job-1" in top.example_links


def test_build_leads_handles_empty_jobs() -> None:
    """Empty job list yields no leads."""
    assert build_leads([]) == []


def test_leads_can_be_written_to_csv(tmp_path: Path) -> None:
    """LeadRow instances can be serialised to CSV with expected column headers."""
    jobs = [{"title": "Data Entry Assistant", "company": "SampleCo",
             "location": "Vancouver, BC", "link": "https://example.com/job-1",
             "published": "", "source": "adzuna"}]
    leads = build_leads(jobs)
    csv_path = tmp_path / "leads.csv"
    fieldnames = ["company", "job_count", "top_keywords", "readiness_score", "example_links"]
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for lead in leads:
            writer.writerow({
                "company": lead.company, "job_count": lead.job_count,
                "top_keywords": lead.top_keywords, "readiness_score": lead.readiness_score,
                "example_links": lead.example_links,
            })
    lines = csv_path.read_text(encoding="utf-8").strip().splitlines()
    assert lines[0].split(",") == fieldnames
    assert "SampleCo" in lines[1]


# ── OpportunityBrief ───────────────────────────────────────────────────────────

def _ev(source: str = "headline") -> EvidenceItem:
    return EvidenceItem(title="Labor shortage hits construction", link="https://ex.com/1", source=source)


def test_brief_fields_populated() -> None:
    """_build_opportunity_brief returns an OpportunityBrief with all fields non-empty."""
    brief = _build_opportunity_brief(
        title="Labor shortages and wage pressure",
        ai_category="Operational efficiency",
        pain_score=7.0,
        evidence=[_ev("headline"), _ev("job")],
        industry="Construction",
    )
    assert isinstance(brief, OpportunityBrief)
    assert brief.likely_buyer
    assert brief.pain_theme
    assert brief.commercial_angle
    assert brief.suggested_next_step
    assert brief.why_now


def test_brief_next_step_high_pain() -> None:
    brief = _build_opportunity_brief(
        title="Manual dispatch bottleneck",
        ai_category="Operational efficiency",
        pain_score=8.5,
        evidence=[_ev()],
        industry="Construction",
    )
    assert "outreach" in brief.suggested_next_step.lower()


def test_brief_next_step_low_pain() -> None:
    brief = _build_opportunity_brief(
        title="Low signal topic",
        ai_category="Market entry",
        pain_score=2.0,
        evidence=[_ev()],
        industry="Retail",
    )
    assert "watch" in brief.suggested_next_step.lower() or "monitor" in brief.suggested_next_step.lower()


def test_brief_why_now_strong_evidence() -> None:
    evidence = [
        EvidenceItem(title=f"Signal {i}", link=f"https://ex.com/{i}", source="headline" if i % 2 == 0 else "job")
        for i in range(4)
    ]
    brief = _build_opportunity_brief(
        title="Test", ai_category="Cost reduction", pain_score=7.0,
        evidence=evidence, industry="Manufacturing",
    )
    # why_now should cite the evidence count
    assert "4" in brief.why_now


def test_brief_buyer_refined_from_job_title() -> None:
    manager_ev = EvidenceItem(
        title="Operations Manager — Construction",
        link="https://ex.com/job1",
        source="job",
    )
    brief = _build_opportunity_brief(
        title="Labor shortage", ai_category="Operational efficiency",
        pain_score=6.0, evidence=[manager_ev], industry="Construction",
    )
    assert "manager" in brief.likely_buyer.lower()


def test_mock_strategy_opportunities_have_brief() -> None:
    headlines = [
        {"title": "Labor shortage hits construction sector", "link": "https://ex.com/h1", "published": ""},
        {"title": "Wage pressure rising for skilled workers", "link": "https://ex.com/h2", "published": ""},
    ]
    jobs = [
        {"title": "Construction Coordinator", "link": "https://ex.com/j1", "published": "", "company": "BuildCo"},
    ]
    strategy = generate_mock_strategy(headlines, "Construction", "Vancouver", jobs=jobs)
    for opp in strategy.opportunity_map:
        assert opp.brief is not None, f"Missing brief on: {opp.title}"
        assert opp.brief.likely_buyer
        assert opp.brief.pain_theme
        assert opp.brief.commercial_angle
        assert opp.brief.suggested_next_step
        assert opp.brief.why_now


def test_brief_serialises_in_to_json_dict() -> None:
    """brief field round-trips through to_json_dict without losing data."""
    strategy = generate_mock_strategy(
        [{"title": "Labor shortage", "link": "https://ex.com/h", "published": ""}],
        "Construction", "Vancouver",
    )
    d = strategy.to_json_dict()
    for opp in d["opportunity_map"]:
        assert "brief" in opp
        if opp["brief"] is not None:
            assert "likely_buyer" in opp["brief"]


def test_markdown_report_includes_brief() -> None:
    strategy = generate_mock_strategy(
        [{"title": "Labor shortage in construction", "link": "https://ex.com/h1", "published": ""}],
        "Construction", "Vancouver",
    )
    md = strategy_to_markdown(strategy)
    assert "Likely buyer" in md
    assert "Suggested next step" in md


def test_html_report_includes_brief() -> None:
    strategy = generate_mock_strategy(
        [{"title": "Labor shortage in construction", "link": "https://ex.com/h1", "published": ""}],
        "Construction", "Vancouver",
    )
    from marketscout.backend.ai.report_html import strategy_to_html
    html = strategy_to_html(strategy)
    assert "Likely buyer" in html
    assert "Why now" in html
