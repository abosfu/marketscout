"""HTML report generator tests."""

import json
from pathlib import Path

import pytest

from marketscout.brain.report_html import strategy_to_html
from marketscout.brain.schema import StrategyOutput


def test_html_report_produces_non_empty_output(sample_strategy_path: Path) -> None:
    """HTML report generator produces non-empty output."""
    data = json.loads(sample_strategy_path.read_text())
    html = strategy_to_html(data)
    assert html
    assert html.strip()
    assert "<!DOCTYPE html>" in html or "<html" in html


def test_html_report_includes_30_60_90_headings(sample_strategy_path: Path) -> None:
    """HTML report includes 30/60/90 plan section headings."""
    data = json.loads(sample_strategy_path.read_text())
    html = strategy_to_html(data)
    assert "30" in html and "60" in html and "90" in html
    assert "30-day" in html or "30/60/90" in html


def test_html_report_never_crashes_on_invalid_input() -> None:
    """HTML report returns safe fallback on invalid data."""
    html = strategy_to_html({})
    assert "Strategy Report" in html or "Unable to validate" in html
    assert "<" in html and ">" in html
