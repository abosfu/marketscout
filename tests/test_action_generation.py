"""Tests for Phase 4: Suggested Actions generation.

Covers:
  - _build_suggested_actions for all recommendation types
  - output count bounds (1–3)
  - content specificity (problem text included)
  - determinism
  - edge cases (padded/deprioritize)
  - integration: all opportunities in strategy output have non-empty actions
  - JSON round-trip preserves suggested_actions
  - DB persistence of suggested_actions
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from marketscout.brain.strategy import _build_suggested_actions, generate_mock_strategy
from marketscout.brain.schema import EvidenceItem, StrategyOutput
from marketscout.db import get_connection, save_run


# ── Helpers ────────────────────────────────────────────────────────────────────

def _actions(
    problem: str = "Labor shortages and wage pressure",
    opportunity_type: str = "operational",
    recommendation: str = "monitor",
    support_level: str = "moderate",
    trend_key: str = "",
) -> list[str]:
    return _build_suggested_actions(
        problem=problem,
        opportunity_type=opportunity_type,
        recommendation=recommendation,
        support_level=support_level,
        trend_key=trend_key,
    )


# ── deprioritize ──────────────────────────────────────────────────────────────

def test_deprioritize_returns_exactly_one_action():
    acts = _actions(recommendation="deprioritize")
    assert len(acts) == 1


def test_deprioritize_contains_no_invest():
    acts = _actions(recommendation="deprioritize")
    assert "do not invest" in acts[0].lower()


def test_deprioritize_ignores_opportunity_type():
    """deprioritize always returns the same action regardless of type."""
    for opp_type in ("operational", "strategic", "compliance"):
        acts = _actions(recommendation="deprioritize", opportunity_type=opp_type)
        assert len(acts) == 1
        assert "do not invest" in acts[0].lower()


# ── pursue_now ────────────────────────────────────────────────────────────────

def test_pursue_now_operational_returns_multiple():
    acts = _actions(recommendation="pursue_now", opportunity_type="operational")
    assert len(acts) >= 2


def test_pursue_now_operational_mentions_leads_or_outbound():
    acts = _actions(recommendation="pursue_now", opportunity_type="operational")
    combined = " ".join(acts).lower()
    assert "leads" in combined or "outbound" in combined or "discovery" in combined


def test_pursue_now_strategic_differs_from_operational():
    ops_acts = _actions(recommendation="pursue_now", opportunity_type="operational")
    str_acts = _actions(recommendation="pursue_now", opportunity_type="strategic")
    assert ops_acts != str_acts


def test_pursue_now_strategic_mentions_buyer_or_competitive():
    acts = _actions(recommendation="pursue_now", opportunity_type="strategic")
    combined = " ".join(acts).lower()
    assert "buyer" in combined or "competitive" in combined or "landscape" in combined


def test_pursue_now_compliance_mentions_regulatory():
    acts = _actions(
        recommendation="pursue_now",
        opportunity_type="compliance",
        problem="Permitting and regulatory delays slowing projects",
    )
    combined = " ".join(acts).lower()
    assert "regulatory" in combined or "compliance" in combined or "enforcement" in combined


def test_pursue_now_includes_problem_text():
    """Actions should reference words from the problem for specificity."""
    acts = _actions(
        recommendation="pursue_now",
        opportunity_type="operational",
        problem="Labor shortages and wage pressure",
    )
    combined = " ".join(acts).lower()
    # Short label derived from problem should appear in at least one action
    assert "labor" in combined or "shortages" in combined or "wage" in combined


# ── validate_further ──────────────────────────────────────────────────────────

def test_validate_further_returns_multiple():
    acts = _actions(recommendation="validate_further")
    assert len(acts) >= 2


def test_validate_further_mentions_interview_or_confirm():
    acts = _actions(recommendation="validate_further")
    combined = " ".join(acts).lower()
    assert "interview" in combined or "confirm" in combined or "validate" in combined


def test_validate_further_mentions_rerun_or_monitor():
    acts = _actions(recommendation="validate_further")
    combined = " ".join(acts).lower()
    assert "re-run" in combined or "2 weeks" in combined or "commit" in combined


# ── monitor ───────────────────────────────────────────────────────────────────

def test_monitor_returns_actions():
    acts = _actions(recommendation="monitor")
    assert len(acts) >= 1


def test_monitor_mentions_alert_or_track():
    acts = _actions(recommendation="monitor")
    combined = " ".join(acts).lower()
    assert "alert" in combined or "track" in combined or "posting" in combined


def test_monitor_uses_trend_key_keyword():
    acts = _actions(
        recommendation="monitor",
        trend_key="operational_efficiency::labor_shortages",
    )
    combined = " ".join(acts).lower()
    assert "labor shortages" in combined


# ── General invariants ────────────────────────────────────────────────────────

def test_all_actions_are_nonempty_strings():
    for rec in ("deprioritize", "pursue_now", "validate_further", "monitor"):
        for opp_type in ("operational", "strategic", "compliance"):
            acts = _actions(recommendation=rec, opportunity_type=opp_type)
            assert acts, f"No actions for {rec}/{opp_type}"
            for a in acts:
                assert isinstance(a, str) and a.strip(), f"Empty action for {rec}/{opp_type}"


def test_action_count_in_range():
    for rec in ("deprioritize", "pursue_now", "validate_further", "monitor"):
        acts = _actions(recommendation=rec)
        assert 1 <= len(acts) <= 3, f"{rec} produced {len(acts)} actions"


def test_actions_are_deterministic():
    """Same inputs always produce the same list."""
    kwargs = dict(
        problem="Supply chain delays impacting construction",
        opportunity_type="operational",
        recommendation="pursue_now",
        support_level="strong",
        trend_key="ops::supply_chain",
    )
    assert _build_suggested_actions(**kwargs) == _build_suggested_actions(**kwargs)


# ── Strategy output integration ───────────────────────────────────────────────

def test_all_strategy_opportunities_have_suggested_actions():
    headlines = [
        {"title": "Labor shortage hits Vancouver", "link": "https://h1.com", "source": "A", "published": ""},
        {"title": "Supply chain delays reported", "link": "https://h2.com", "source": "B", "published": ""},
        {"title": "Permit delays slow construction", "link": "https://h3.com", "source": "C", "published": ""},
    ]
    jobs = [
        {"title": "Construction Coordinator", "company": "Co", "link": "https://j1.com", "published": "", "source": ""},
    ]
    strategy = generate_mock_strategy(headlines, "Construction", "Vancouver", jobs=jobs)
    for opp in strategy.opportunity_map:
        assert hasattr(opp, "suggested_actions")
        assert isinstance(opp.suggested_actions, list)
        assert len(opp.suggested_actions) >= 1, f"Empty actions for: {opp.title}"
        for act in opp.suggested_actions:
            assert isinstance(act, str) and act.strip()


def test_padded_opportunities_have_deprioritize_action():
    """Template-padded opportunities should always carry the deprioritize action."""
    strategy = generate_mock_strategy([], "Construction", "Vancouver")
    padded = [o for o in strategy.opportunity_map if o.is_padded]
    assert padded, "Expected some padded opportunities with empty headline input"
    for opp in padded:
        assert opp.suggested_actions
        assert "do not invest" in opp.suggested_actions[0].lower()


def test_suggested_actions_json_roundtrip():
    strategy = generate_mock_strategy(
        [{"title": "Labor shortage", "link": "https://h.com", "source": "A", "published": ""}],
        "Construction", "Vancouver",
    )
    d = strategy.to_json_dict()
    restored = StrategyOutput.model_validate(d)
    for orig, rest in zip(strategy.opportunity_map, restored.opportunity_map):
        assert orig.suggested_actions == rest.suggested_actions


# ── DB persistence ────────────────────────────────────────────────────────────

def _make_run_strategy_with_actions():
    from marketscout.brain.schema import (
        BusinessCase, DataQuality, EvidenceItem, OpportunityItem,
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
        suggested_actions=[
            "Pull top companies from leads.csv",
            "Book 3 discovery calls this sprint",
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
        signals_used=SignalsUsed(headlines_count=3, jobs_count=1),
        data_quality=DataQuality(freshness_window_days=7, coverage_score=0.7, source_mix_score=0.6),
    )


def test_db_persists_suggested_actions():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    conn = get_connection(Path(tmp.name))
    strategy = _make_run_strategy_with_actions()
    save_run(
        conn, "act-run-1", "Vancouver", "Construction", strategy,
        [], [], {"headlines": {}, "jobs": {}},
        {"started_at_iso": "2024-01-01T00:00:00Z", "deterministic": False},
        "deterministic",
    )
    row = conn.execute(
        "SELECT suggested_actions FROM opportunities WHERE title = 'Labor shortages'"
    ).fetchone()
    assert row is not None
    stored = json.loads(row["suggested_actions"])
    assert isinstance(stored, list)
    assert len(stored) == 2
    assert "leads.csv" in stored[0]


def test_db_suggested_actions_roundtrip_preserves_all_items():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    conn = get_connection(Path(tmp.name))
    strategy = _make_run_strategy_with_actions()
    save_run(
        conn, "act-run-2", "Vancouver", "Construction", strategy,
        [], [], {"headlines": {}, "jobs": {}},
        {"started_at_iso": "2024-01-01T00:00:00Z", "deterministic": False},
        "deterministic",
    )
    row = conn.execute(
        "SELECT suggested_actions FROM opportunities WHERE title = 'Labor shortages'"
    ).fetchone()
    stored = json.loads(row["suggested_actions"])
    expected = strategy.opportunity_map[0].suggested_actions
    assert stored == expected
