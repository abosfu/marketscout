"""Pytest configuration and shared fixtures."""

from pathlib import Path

import pytest

# All sample data for tests lives here.
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture(autouse=True)
def _unset_optional_scout_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep headline/job tests on mocked RSS paths when developer keys are loaded."""
    monkeypatch.delenv("NEWSAPI_KEY", raising=False)
    monkeypatch.delenv("SERPAPI_KEY", raising=False)


@pytest.fixture
def repo_root() -> Path:
    """Repository root (parent of tests/)."""
    return Path(__file__).resolve().parent.parent


@pytest.fixture
def sample_strategy_v2_path() -> Path:
    """V2.0 sample strategy JSON for schema / report tests."""
    return FIXTURES_DIR / "sample_strategy_v2.json"
