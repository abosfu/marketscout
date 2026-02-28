"""Schema validation tests."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from marketscout.brain.schema import StrategyOutput, get_json_schema


def test_strategy_output_validates_sample_strategy(sample_strategy_path: Path) -> None:
    """Sample strategy JSON conforms to StrategyOutput schema."""
    data = json.loads(sample_strategy_path.read_text())
    strategy = StrategyOutput.model_validate(data)
    assert strategy.pain_score >= 1 and strategy.pain_score <= 10
    assert 4 <= len(strategy.problems) <= 6
    assert strategy.strategy_version in ("1.0", "1.1")
    assert len(strategy.ai_matches) >= 1
    assert len(strategy.plan_30_60_90) == 3
    assert strategy.roi_notes.ranges
    assert len(strategy.roi_notes.assumptions) >= 1


def test_strategy_output_rejects_invalid_pain_score() -> None:
    """Pain score must be 1–10."""
    data = {
        "strategy_version": "1.0",
        "pain_score": 0,
        "problems": [
            {"problem": "P1", "evidence_headline": "H1", "evidence_link": "https://x.com/1"},
            {"problem": "P2", "evidence_headline": "H2", "evidence_link": "https://x.com/2"},
            {"problem": "P3", "evidence_headline": "H3", "evidence_link": "https://x.com/3"},
            {"problem": "P4", "evidence_headline": "H4", "evidence_link": "https://x.com/4"},
        ],
        "ai_matches": [{"category": "C1", "recommended_approach": "R1"}],
        "plan_30_60_90": [
            {"phase": "30-day", "actions": ["a"]},
            {"phase": "60-day", "actions": ["b"]},
            {"phase": "90-day", "actions": ["c"]},
        ],
        "roi_notes": {"ranges": "10-20%", "assumptions": ["A1"]},
    }
    with pytest.raises(ValidationError):
        StrategyOutput.model_validate(data)


def test_get_json_schema_returns_dict() -> None:
    """get_json_schema returns a valid JSON schema dict."""
    schema = get_json_schema()
    assert isinstance(schema, dict)
    assert "properties" in schema or "title" in schema
    # Round-trip
    json.dumps(schema)
