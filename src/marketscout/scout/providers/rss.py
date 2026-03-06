"""RSS jobs provider: best-effort job-related listings from Google News RSS."""

from __future__ import annotations

import time
import urllib.parse
import xml.etree.ElementTree as ET
from typing import Any

import requests

from marketscout.scout.errors import ScoutError

from .base import JobItem, JobsProvider

DEFAULT_JOBS_LIMIT = 10
REQUEST_TIMEOUT = 10
RETRIES = 2
RETRY_BACKOFF = 1.0


def _normalize_job(item: dict[str, Any]) -> JobItem:
    """Normalize a job item to title, company, location, link, published, source."""
    return {
        "title": (item.get("title") or "").strip(),
        "company": (item.get("company") or "").strip(),
        "location": (item.get("location") or "").strip(),
        "link": (item.get("link") or "").strip() or "#",
        "published": (item.get("published") or "").strip(),
        "source": (item.get("source") or "").strip(),
    }


class RssJobsProvider(JobsProvider):
    """JobsProvider implementation using Google News RSS as a jobs-like signal."""

    def fetch_jobs(self, city: str, industry: str, limit: int) -> list[JobItem]:
        """
        Fetch job-related items from public RSS (e.g. news about jobs). Retries with backoff.
        Raises ScoutError on failure. No sample fallback at runtime.
        Returns list of normalized job dicts (title, company, location, link, published, source).
        """
        city = (city or "Vancouver").strip()
        industry = (industry or "construction").strip()
        q = f"{city} {industry} jobs"
        params = {"q": q, "hl": "en-CA", "gl": "CA", "ceid": "CA:en"}
        url = "https://news.google.com/rss/search?" + urllib.parse.urlencode(params)
        last_err: Exception | None = None
        for attempt in range(RETRIES + 1):
            try:
                resp = requests.get(url, timeout=REQUEST_TIMEOUT)
                resp.raise_for_status()
                root = ET.fromstring(resp.text)
                channel = root.find("channel")
                if channel is None:
                    return []
                items: list[dict[str, Any]] = []
                for item in channel.findall("item")[:limit]:
                    title_el = item.find("title")
                    link_el = item.find("link")
                    pub_el = item.find("pubDate")
                    title = (title_el.text or "").strip() if title_el is not None else ""
                    link = (link_el.text or "").strip() if link_el is not None else "#"
                    published = (pub_el.text or "").strip() if pub_el is not None else ""
                    if title:
                        items.append(
                            {
                                "title": title,
                                "company": "",
                                "location": city,
                                "link": link,
                                "published": published,
                                "source": "rss",
                            }
                        )
                return [_normalize_job(i) for i in items[:limit]]
            except (requests.RequestException, ET.ParseError) as e:
                last_err = e
                if attempt < RETRIES:
                    time.sleep(RETRY_BACKOFF)
        raise ScoutError(
            f"Failed to fetch jobs via RSS after {RETRIES + 1} attempts. "
            f"Check network and URL. Error: {last_err}"
        ) from last_err

