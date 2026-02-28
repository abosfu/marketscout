"""Headlines (scout) parsing tests."""

from pathlib import Path

import pytest

from marketscout.scout.headlines import _parse_rss_items, fetch_headlines


def test_parse_rss_items_returns_list_of_dicts() -> None:
    """Parsing valid RSS returns list of dicts with title, source, link, published."""
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
    """Limit caps number of items returned."""
    rss = """<?xml version="1.0"?>
<rss><channel>
  <item><title>A</title><link>#</link></item>
  <item><title>B</title><link>#</link></item>
  <item><title>C</title><link>#</link></item>
</channel></rss>"""
    assert len(_parse_rss_items(rss, limit=2)) == 2
    assert len(_parse_rss_items(rss, limit=10)) == 3


def test_parse_rss_items_invalid_xml_raises() -> None:
    """Invalid XML raises ScoutError."""
    from marketscout.scout.headlines import ScoutError

    with pytest.raises(ScoutError):
        _parse_rss_items("not xml at all", limit=10)


def test_fetch_headlines_returns_list(monkeypatch: pytest.MonkeyPatch) -> None:
    """fetch_headlines returns a list when request returns valid RSS."""
    from marketscout.scout.headlines import fetch_headlines

    rss = """<?xml version="1.0"?><rss><channel>
  <item><title>T1</title><link>https://a.com</link></item>
  <item><title>T2</title><link>https://b.com</link></item>
</channel></rss>"""

    class FakeResponse:
        text = rss
        def raise_for_status(self): pass

    def fake_get(*args, **kwargs):
        return FakeResponse()

    monkeypatch.setattr("marketscout.scout.headlines.requests.get", fake_get)
    result = fetch_headlines(limit=3)
    assert isinstance(result, list)
    assert len(result) >= 1
    for item in result:
        assert "title" in item and "link" in item and "source" in item and "published" in item


def test_parse_rss_items_on_saved_fixture(repo_root: Path) -> None:
    """RSS parsing works on saved sample RSS fixture (tests only)."""
    fixture = repo_root / "tests" / "fixtures" / "sample_rss.xml"
    assert fixture.exists(), "tests/fixtures/sample_rss.xml required"
    raw = fixture.read_text()
    items = _parse_rss_items(raw, limit=10)
    assert len(items) == 3
    assert items[0]["title"] == "Vancouver construction sector faces labor shortages"
    assert items[0]["link"] == "https://example.com/1"
    assert items[1]["source"] == "Reuters"
    assert "published" in items[2]
