"""Demo mode and CLI demo tests."""

import json
from pathlib import Path

import pytest

from marketscout.brain import generate_strategy
from marketscout.brain.schema import StrategyOutput


def test_demo_mode_generation_produces_valid_schema(repo_root: Path) -> None:
    """Generating strategy from demo data (sample headlines + jobs) produces valid StrategyOutput."""
    data_dir = repo_root / "data"
    headlines_path = data_dir / "sample_headlines.json"
    jobs_path = data_dir / "sample_jobs.json"
    headlines: list = []
    jobs: list = []
    if headlines_path.exists():
        headlines = json.loads(headlines_path.read_text())
    if jobs_path.exists():
        jobs = json.loads(jobs_path.read_text())
    strategy = generate_strategy(
        headlines,
        industry="Construction",
        objective="Market entry",
        location="Vancouver, BC",
        jobs=jobs,
        force_mock=True,
    )
    assert isinstance(strategy, StrategyOutput)
    assert 1 <= strategy.pain_score <= 10
    assert 4 <= len(strategy.problems) <= 6
    assert strategy.strategy_version in ("1.0", "1.1")


def test_cli_demo_writes_demo_input_and_demo_strategy(tmp_path: Path) -> None:
    """CLI demo command writes demo_input.json and demo_strategy.json successfully."""
    # Create minimal sample files so cmd_demo has something to read
    (tmp_path / "sample_headlines.json").write_text(
        json.dumps([{"title": "Test headline", "link": "https://x.com", "source": "", "published": ""}]),
        encoding="utf-8",
    )
    (tmp_path / "sample_jobs.json").write_text(
        json.dumps([{"title": "Test job", "company": "Co", "location": "Vancouver", "link": "https://y.com", "published": "", "source": ""}]),
        encoding="utf-8",
    )
    from marketscout.cli import cmd_demo

    exit_code = cmd_demo(tmp_path)
    assert exit_code == 0
    demo_input_path = tmp_path / "demo_input.json"
    demo_strategy_path = tmp_path / "demo_strategy.json"
    assert demo_input_path.exists()
    assert demo_strategy_path.exists()
    demo_input = json.loads(demo_input_path.read_text())
    assert "headlines" in demo_input
    assert "jobs" in demo_input
    demo_strategy = json.loads(demo_strategy_path.read_text())
    strategy = StrategyOutput.model_validate(demo_strategy)
    assert 1 <= strategy.pain_score <= 10
    assert 4 <= len(strategy.problems) <= 6
