"""Pytest configuration and shared fixtures."""

from pathlib import Path

import pytest


@pytest.fixture
def repo_root() -> Path:
    """Repository root (parent of tests/)."""
    return Path(__file__).resolve().parent.parent


@pytest.fixture
def sample_headlines_path(repo_root: Path) -> Path:
    return repo_root / "data" / "sample_headlines.json"


@pytest.fixture
def sample_strategy_path(repo_root: Path) -> Path:
    return repo_root / "data" / "sample_strategy.json"
