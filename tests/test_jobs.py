"""Jobs Scout tests: normalization and fetch with mocked request."""

import json
from pathlib import Path

import pytest

from marketscout.scout.jobs import _normalize_job, fetch_jobs


def test_normalize_job_returns_expected_fields() -> None:
    """Normalized job has title, company, location, link, published, source."""
    raw = {
        "title": "Site Superintendent",
        "company": "ABC Ltd",
        "location": "Vancouver, BC",
        "link": "https://example.com/1",
        "published": "2025-02-24",
        "source": "sample",
    }
    out = _normalize_job(raw)
    assert out["title"] == "Site Superintendent"
    assert out["company"] == "ABC Ltd"
    assert out["location"] == "Vancouver, BC"
    assert out["link"] == "https://example.com/1"
    assert out["published"] == "2025-02-24"
    assert out["source"] == "sample"


def test_sample_jobs_fixture_loads_and_normalizes(repo_root: Path) -> None:
    """Loading data/sample_jobs.json (fixture) yields list of dicts with expected keys."""
    path = repo_root / "data" / "sample_jobs.json"
    if not path.exists():
        pytest.skip("data/sample_jobs.json not found")
    data = json.loads(path.read_text())
    assert isinstance(data, list)
    for item in data:
        normalized = _normalize_job(item)
        assert "title" in normalized and "link" in normalized
        assert "company" in normalized and "location" in normalized and "source" in normalized


def test_fetch_jobs_returns_list_when_mocked(monkeypatch: pytest.MonkeyPatch) -> None:
    """fetch_jobs returns a list when RSS request is mocked."""
    import xml.etree.ElementTree as ET

    rss = """<?xml version="1.0"?><rss><channel>
  <item><title>Job A</title><link>https://a.com</link><pubDate>Today</pubDate></item>
</channel></rss>"""

    class FakeResponse:
        text = rss
        def raise_for_status(self): pass

    monkeypatch.setattr("marketscout.scout.jobs.requests.get", lambda *a, **k: FakeResponse())
    result = fetch_jobs(city="Vancouver", industry="Construction", limit=5)
    assert isinstance(result, list)
    for item in result:
        assert "title" in item and "link" in item
