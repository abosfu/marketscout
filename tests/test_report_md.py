"""Markdown report generator tests."""

from pathlib import Path

import pytest

from marketscout.brain.report_md import strategy_to_markdown
from marketscout.brain.schema import StrategyOutput


def test_report_produces_non_empty_output(sample_strategy_path: Path) -> None:
    """Report generator produces non-empty Markdown."""
    import json
    data = json.loads(sample_strategy_path.read_text())
    md = strategy_to_markdown(data)
    assert md
    assert md.strip()


def test_report_includes_30_60_90_headings(sample_strategy_path: Path) -> None:
    """Report includes 30/60/90 plan section headings."""
    import json
    data = json.loads(sample_strategy_path.read_text())
    md = strategy_to_markdown(data)
    assert "30/60/90" in md or "30" in md
    assert "60" in md
    assert "90" in md


def test_report_accepts_strategy_output_object() -> None:
    """Report accepts StrategyOutput instance."""
    strategy = StrategyOutput(
        strategy_version="1.0",
        pain_score=5,
        problems=[
            {"problem": "P1", "evidence_headline": "H1", "evidence_link": "https://x.com/1"},
            {"problem": "P2", "evidence_headline": "H2", "evidence_link": "https://x.com/2"},
            {"problem": "P3", "evidence_headline": "H3", "evidence_link": "https://x.com/3"},
            {"problem": "P4", "evidence_headline": "H4", "evidence_link": "https://x.com/4"},
        ],
        ai_matches=[{"category": "C1", "recommended_approach": "R1"}],
        plan_30_60_90=[
            {"phase": "30-day", "actions": ["a"]},
            {"phase": "60-day", "actions": ["b"]},
            {"phase": "90-day", "actions": ["c"]},
        ],
        roi_notes={"ranges": "10-20%", "assumptions": ["A1"]},
    )
    md = strategy_to_markdown(strategy)
    assert "Executive Summary" in md
    assert "Opportunity Map" in md
    assert "Sources" in md


def test_report_never_crashes_on_invalid_input() -> None:
    """Report returns safe fallback on invalid data instead of raising."""
    md = strategy_to_markdown({})
    assert "Strategy Report" in md or "Unable to validate" in md


def test_report_includes_signals_used_and_score_breakdown() -> None:
    """Report includes 'Signals Used' and 'Score Breakdown' when present."""
    from marketscout.brain.schema import (
        ScoreBreakdown,
        SignalsUsed,
        StrategyOutput,
    )
    strategy = StrategyOutput(
        strategy_version="1.1",
        pain_score=6,
        signals_used=SignalsUsed(headlines_count=5, jobs_count=3, econ_used=False),
        score_breakdown=ScoreBreakdown(
            news_signal_score=5,
            jobs_signal_score=4,
            combined_pain_score=6,
            weights={"news": 0.6, "jobs": 0.4},
        ),
        problems=[
            {"problem": "P1", "evidence_headline": "H1", "evidence_link": "https://x.com/1"},
            {"problem": "P2", "evidence_headline": "H2", "evidence_link": "https://x.com/2"},
            {"problem": "P3", "evidence_headline": "H3", "evidence_link": "https://x.com/3"},
            {"problem": "P4", "evidence_headline": "H4", "evidence_link": "https://x.com/4"},
        ],
        ai_matches=[{"category": "C1", "recommended_approach": "R1"}],
        plan_30_60_90=[
            {"phase": "30-day", "actions": ["a"]},
            {"phase": "60-day", "actions": ["b"]},
            {"phase": "90-day", "actions": ["c"]},
        ],
        roi_notes={"ranges": "10-20%", "assumptions": ["A1"]},
    )
    md = strategy_to_markdown(strategy)
    assert "Signals Used" in md
    assert "Score Breakdown" in md
    assert "30/60/90" in md or "30" in md
