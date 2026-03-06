"""Pytest configuration and shared fixtures."""

from pathlib import Path

import pytest

# All sample data lives here — never under data/ which is runtime-empty.
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def repo_root() -> Path:
    """Repository root (parent of tests/)."""
    return Path(__file__).resolve().parent.parent


@pytest.fixture
def sample_strategy_v2_path() -> Path:
    """V2.0 sample strategy JSON for schema / report tests."""
    return FIXTURES_DIR / "sample_strategy_v2.json"
