"""Scout tests: RSS headline parsing, job normalization/fetching, and Adzuna provider."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

import pytest

from marketscout.scout import ScoutError
from marketscout.scout.headlines import _parse_rss_items, fetch_headlines
import marketscout.scout.headlines as _ms_headlines
from marketscout.scout.jobs import _normalize_job, fetch_jobs
from marketscout.scout.providers.adzuna import AdzunaProvider
import marketscout.scout.providers.adzuna as _ms_adzuna
import marketscout.scout.providers.rss as _ms_rss


# ── Headlines ─────────────────────────────────────────────────────────────────

def test_parse_rss_items_returns_list_of_dicts() -> None:
    """Parsing valid RSS returns dicts with title, source, link, and published."""
    rss = """<?xml version="1.0"?>
<rss><channel>
  <item>
    <title>First Headline</title>
    <link>https://example.com/1</link>
    <source url="https://source.com">Source One</source>
    <pubDate>Mon, 01 Jan 2024 12:00:00 GMT</pubDate>
  </item>
  <item>
    <title>Second Headline</title>
    <link>https://example.com/2</link>
    <pubDate>Tue, 02 Jan 2024 12:00:00 GMT</pubDate>
  </item>
</channel></rss>"""
    items = _parse_rss_items(rss, limit=10)
    assert len(items) == 2
    assert items[0]["title"] == "First Headline"
    assert items[0]["link"] == "https://example.com/1"
    assert "published" in items[0]
    assert items[1]["title"] == "Second Headline"
    assert items[1]["source"] == ""


def test_parse_rss_items_respects_limit() -> None:
    """limit parameter caps the number of items returned."""
    rss = """<?xml version="1.0"?>
<rss><channel>
  <item><title>A</title><link>#</link></item>
  <item><title>B</title><link>#</link></item>
  <item><title>C</title><link>#</link></item>
</channel></rss>"""
    assert len(_parse_rss_items(rss, limit=2)) == 2
    assert len(_parse_rss_items(rss, limit=10)) == 3


def test_parse_rss_items_invalid_xml_raises() -> None:
    """Malformed XML raises ScoutError."""
    with pytest.raises(ScoutError):
        _parse_rss_items("not xml at all", limit=10)


def test_fetch_headlines_returns_list(monkeypatch: pytest.MonkeyPatch) -> None:
    """fetch_headlines returns a list of dicts when the HTTP response is valid RSS."""
    rss = """<?xml version="1.0"?><rss><channel>
  <item><title>T1</title><link>https://a.com</link></item>
  <item><title>T2</title><link>https://b.com</link></item>
</channel></rss>"""

    class FakeResponse:
        text = rss
        def raise_for_status(self): pass

    monkeypatch.setattr(_ms_headlines.requests, "get", lambda *a, **k: FakeResponse())
    result = fetch_headlines(limit=3)
    assert isinstance(result, list) and len(result) >= 1
    for item in result:
        assert "title" in item and "link" in item and "source" in item and "published" in item


def test_parse_rss_items_on_saved_fixture(repo_root: Path) -> None:
    """RSS parsing works on tests/fixtures/sample_rss.xml."""
    fixture = repo_root / "tests" / "fixtures" / "sample_rss.xml"
    assert fixture.exists(), "tests/fixtures/sample_rss.xml required"
    items = _parse_rss_items(fixture.read_text(), limit=10)
    assert len(items) == 3
    assert items[0]["title"] == "Vancouver construction sector faces labor shortages"
    assert items[0]["link"] == "https://example.com/1"
    assert items[1]["source"] == "Reuters"
    assert "published" in items[2]


# ── Jobs ──────────────────────────────────────────────────────────────────────

def test_normalize_job_returns_expected_fields() -> None:
    """_normalize_job preserves all standard fields."""
    raw = {
        "title": "Site Superintendent", "company": "ABC Ltd",
        "location": "Vancouver, BC", "link": "https://example.com/1",
        "published": "2025-02-24", "source": "sample",
    }
    out = _normalize_job(raw)
    assert out["title"] == "Site Superintendent"
    assert out["company"] == "ABC Ltd"
    assert out["location"] == "Vancouver, BC"
    assert out["link"] == "https://example.com/1"
    assert out["published"] == "2025-02-24"
    assert out["source"] == "sample"


def test_sample_jobs_fixture_loads_and_normalizes() -> None:
    """tests/fixtures/sample_jobs.json loads and each item normalizes without error."""
    path = Path(__file__).resolve().parent / "fixtures" / "sample_jobs.json"
    if not path.exists():
        pytest.skip("tests/fixtures/sample_jobs.json not found")
    data = json.loads(path.read_text())
    assert isinstance(data, list)
    for item in data:
        normalized = _normalize_job(item)
        assert "title" in normalized and "link" in normalized
        assert "company" in normalized and "location" in normalized and "source" in normalized


def test_fetch_jobs_returns_list_when_mocked(monkeypatch: pytest.MonkeyPatch) -> None:
    """fetch_jobs returns a list of dicts when the RSS provider request is mocked."""
    rss = """<?xml version="1.0"?><rss><channel>
  <item><title>Job A</title><link>https://a.com</link><pubDate>Today</pubDate></item>
</channel></rss>"""

    class FakeResponse:
        text = rss
        def raise_for_status(self) -> None: pass

    monkeypatch.setattr(_ms_rss.requests, "get", lambda *a, **k: FakeResponse())
    result = fetch_jobs(city="Vancouver", industry="Construction", limit=5, provider="rss")
    assert isinstance(result, list)
    for item in result:
        assert "title" in item and "link" in item


# ── Adzuna provider ───────────────────────────────────────────────────────────

def test_adzuna_provider_raises_when_keys_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """AdzunaProvider() without env keys raises ScoutError naming both variables."""
    monkeypatch.delenv("ADZUNA_APP_ID", raising=False)
    monkeypatch.delenv("ADZUNA_APP_KEY", raising=False)
    with pytest.raises(ScoutError) as exc:
        AdzunaProvider()
    msg = str(exc.value)
    assert "ADZUNA_APP_ID" in msg and "ADZUNA_APP_KEY" in msg


def test_adzuna_provider_parses_results(monkeypatch: pytest.MonkeyPatch) -> None:
    """AdzunaProvider.fetch_jobs parses API JSON into normalised JobItem dicts."""
    class FakeResp:
        def raise_for_status(self) -> None: pass
        def json(self) -> Dict[str, Any]:
            return {"results": [{
                "title": "Site Coordinator",
                "company": {"display_name": "Contoso Construction"},
                "location": {"display_name": "Vancouver, BC"},
                "redirect_url": "https://example.com/job/123",
                "created": "2025-02-24T10:00:00Z",
            }]}

    monkeypatch.setattr(_ms_adzuna.requests, "get", lambda *a, **k: FakeResp())
    provider = AdzunaProvider(app_id="test-id", app_key="test-key", country="ca")
    jobs = provider.fetch_jobs(city="Vancouver", industry="Construction", limit=5)
    assert isinstance(jobs, list) and len(jobs) == 1
    job = jobs[0]
    assert job["title"] == "Site Coordinator"
    assert job["company"] == "Contoso Construction"
    assert job["location"] == "Vancouver, BC"
    assert job["link"] == "https://example.com/job/123"
    assert job["published"] == "2025-02-24T10:00:00Z"
    assert job["source"] == "adzuna"
