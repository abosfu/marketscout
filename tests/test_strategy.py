"""Mock strategy generation tests."""

import pytest

from marketscout.brain.schema import StrategyOutput
from marketscout.brain.strategy import generate_mock_strategy, generate_strategy


def test_generate_mock_strategy_returns_valid_schema() -> None:
    """Mock strategy generator produces schema-valid StrategyOutput."""
    headlines = [
        {"title": "Labor shortage in Vancouver", "link": "https://a.com", "source": "A"},
        {"title": "Housing crisis and rates", "link": "https://b.com", "source": "B"},
        {"title": "Supply chain issues", "link": "https://c.com", "source": "C"},
    ]
    strategy = generate_mock_strategy(
        headlines,
        industry="Construction",
        objective="Market entry",
        location="Vancouver, BC",
    )
    assert isinstance(strategy, StrategyOutput)
    assert 1 <= strategy.pain_score <= 10
    assert 4 <= len(strategy.problems) <= 6
    assert strategy.strategy_version == "1.1"
    assert strategy.signals_used is not None
    assert strategy.score_breakdown is not None
    assert 0 <= strategy.score_breakdown.news_signal_score <= 10
    assert 0 <= strategy.score_breakdown.jobs_signal_score <= 10
    assert 1 <= strategy.score_breakdown.combined_pain_score <= 10
    assert len(strategy.ai_matches) >= 1
    assert len(strategy.plan_30_60_90) == 3
    assert strategy.roi_notes.ranges
    assert len(strategy.roi_notes.assumptions) >= 1


def test_generate_mock_strategy_works_with_empty_headlines() -> None:
    """Mock strategy works with no headlines (fallback content)."""
    strategy = generate_mock_strategy(
        [],
        industry="Technology",
        objective="Growth and scale",
        location="Vancouver, BC",
    )
    assert isinstance(strategy, StrategyOutput)
    assert 4 <= len(strategy.problems) <= 6
    assert strategy.plan_30_60_90[0].phase == "30-day"
    assert strategy.plan_30_60_90[-1].phase == "90-day"


def test_generate_strategy_force_mock_returns_mock() -> None:
    """generate_strategy with force_mock=True always returns mock (no LLM)."""
    strategy = generate_strategy(
        [{"title": "Test", "link": "#", "source": ""}],
        industry="Retail",
        objective="Cost reduction",
        location="Toronto, ON",
        force_mock=True,
    )
    assert isinstance(strategy, StrategyOutput)
    assert 4 <= len(strategy.problems) <= 6
