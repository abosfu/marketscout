"""CLI run command: writes strategy.json, report.md, report.html."""

from pathlib import Path

import pytest


def test_cli_run_creates_output_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """run command creates out_dir/strategy.json, report.md, report.html when fetch is mocked."""
    from marketscout.cli import cmd_run

    rss = """<?xml version="1.0"?><rss><channel>
  <item><title>Headline A</title><link>https://a.com</link></item>
  <item><title>Headline B</title><link>https://b.com</link></item>
</channel></rss>"""

    class FakeResp:
        text = rss
        def raise_for_status(self): pass

    def fake_get(*args, **kwargs):
        return FakeResp()

    monkeypatch.setattr("marketscout.scout.headlines.requests.get", fake_get)
    monkeypatch.setattr("marketscout.scout.jobs.requests.get", fake_get)

    out_dir = tmp_path / "out"
    exit_code = cmd_run(
        industry="Construction",
        objective="Market entry",
        city="Vancouver",
        location="Vancouver, BC",
        out_dir=out_dir,
        jobs_limit=5,
    )
    assert exit_code == 0
    assert (out_dir / "strategy.json").exists()
    assert (out_dir / "report.md").exists()
    assert (out_dir / "report.html").exists()
    strategy_content = (out_dir / "strategy.json").read_text()
    assert "pain_score" in strategy_content
    assert "problems" in strategy_content
    md = (out_dir / "report.md").read_text()
    assert "Executive Summary" in md or "Pain" in md
    html = (out_dir / "report.html").read_text()
    assert "<" in html and "30" in html
