"""Fetch and parse business headlines from Google News RSS (no API key). Live only; no sample fallback at runtime."""

from __future__ import annotations

import time
import urllib.parse
import xml.etree.ElementTree as ET
from typing import NoReturn

import requests

from marketscout.config import get_default_city, get_max_headlines
from marketscout.scout.errors import ScoutError

GOOGLE_NEWS_RSS_BASE = "https://news.google.com/rss/search"
DEFAULT_LIMIT = 10
REQUEST_TIMEOUT = 15
RETRIES = 2
RETRY_BACKOFF = 1.0


def build_rss_url(
    city: str | None = None,
    industry: str | None = None,
    hl: str = "en-CA",
    gl: str = "CA",
    ceid: str = "CA:en",
) -> str:
    """Build Google News RSS URL with optional query parameters."""
    city = (city or get_default_city()).strip() or "Vancouver"
    parts = [city]
    if industry and industry.strip():
        parts.append(industry.strip())
    else:
        parts.append("business")
    q = " ".join(parts)
    params = {"q": q, "hl": hl, "gl": gl, "ceid": ceid}
    query = urllib.parse.urlencode(params)
    return f"{GOOGLE_NEWS_RSS_BASE}?{query}"


def _parse_rss_items(raw_xml: str, limit: int = DEFAULT_LIMIT) -> list[dict[str, str]]:
    """Parse RSS XML string into list of items with title, source, link, published."""
    items: list[dict[str, str]] = []
    try:
        root = ET.fromstring(raw_xml)
    except ET.ParseError as e:
        raise ScoutError(f"Failed to parse RSS XML: {e}") from e
    ns = {}
    channel = root.find("channel", ns)
    if channel is None:
        channel = root
    for item in channel.findall("item", ns)[: limit * 2]:
        title_el = item.find("title", ns)
        link_el = item.find("link", ns)
        source_el = item.find("source", ns)
        pub_el = item.find("pubDate", ns)
        title = (title_el.text or "").strip() if title_el is not None else ""
        link = (link_el.text or "").strip() if link_el is not None else ""
        source = (source_el.text or "").strip() if source_el is not None else ""
        if not source and source_el is not None:
            source = source_el.get("url", "")
        published = (pub_el.text or "").strip() if pub_el is not None else ""
        items.append({
            "title": title,
            "source": source,
            "link": link,
            "published": published,
        })
        if len(items) >= limit:
            break
    return items[:limit]


def _normalize_dedupe_headlines(items: list[dict[str, str]]) -> list[dict[str, str]]:
    """Normalize and deduplicate by title (case-insensitive strip)."""
    seen: set[str] = set()
    out: list[dict[str, str]] = []
    for h in items:
        title = (h.get("title") or "").strip()
        key = title.lower()
        if key and key not in seen:
            seen.add(key)
            out.append({
                "title": title,
                "source": (h.get("source") or "").strip(),
                "link": (h.get("link") or "").strip(),
                "published": (h.get("published") or "").strip(),
            })
    return out


def fetch_headlines(
    url: str | None = None,
    limit: int | None = None,
    timeout: int = REQUEST_TIMEOUT,
    city: str | None = None,
    industry: str | None = None,
) -> list[dict[str, str]]:
    """
    Fetch headlines from Google News RSS. Retries up to RETRIES with backoff.
    Raises ScoutError on network or parse failure. No sample fallback at runtime.
    """
    limit = limit if limit is not None else get_max_headlines()
    if url is None:
        url = build_rss_url(city=city, industry=industry)
    last_err: Exception | None = None
    for attempt in range(RETRIES + 1):
        try:
            resp = requests.get(url, timeout=timeout)
            resp.raise_for_status()
            items = _parse_rss_items(resp.text, limit=limit)
            items = _normalize_dedupe_headlines(items)
            return items
        except requests.RequestException as e:
            last_err = e
            if attempt < RETRIES:
                time.sleep(RETRY_BACKOFF)
        except ScoutError:
            raise
    raise ScoutError(
        f"Failed to fetch headlines after {RETRIES + 1} attempts. "
        f"Check network and URL: {url}. Error: {last_err}"
    ) from last_err


# Legacy default URL for backward compatibility
VANCOUVER_BUSINESS_RSS = build_rss_url(city="Vancouver", industry="business")
