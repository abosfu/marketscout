"""SerpAPI Google Jobs provider via SerpApi ``engine=google_jobs``.

Requires ``SERPAPI_KEY`` (see ``marketscout.config.get_serpapi_key``).
"""

from __future__ import annotations

from typing import Any

import requests

from marketscout.config import get_serpapi_key
from marketscout.scout.errors import ScoutError

from .base import JobItem, JobsProvider

SERPAPI_URL = "https://serpapi.com/search.json"
REQUEST_TIMEOUT = 15


class SerpApiJobsProvider(JobsProvider):
    """JobsProvider backed by SerpAPI Google Jobs search."""

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = (api_key or get_serpapi_key()).strip()
        if not self.api_key:
            raise ScoutError(
                "SerpAPI jobs provider requires SERPAPI_KEY in the environment."
            )

    def fetch_jobs(self, city: str, industry: str, limit: int) -> list[JobItem]:
        """Fetch jobs from Google Jobs via SerpAPI; normalized JobItem dicts."""
        city = (city or "").strip()
        industry = (industry or "").strip()
        q = f"{industry} jobs {city}".strip()
        params: dict[str, Any] = {
            "engine": "google_jobs",
            "q": q or "jobs",
            "api_key": self.api_key,
        }

        try:
            resp = requests.get(SERPAPI_URL, params=params, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as e:
            raise ScoutError(f"SerpAPI Google Jobs request failed: {e}") from e
        except ValueError as e:
            raise ScoutError(f"SerpAPI Google Jobs response was not valid JSON: {e}") from e

        err = (data.get("error") or "").strip()
        if err:
            raise ScoutError(f"SerpAPI Google Jobs error: {err}")

        raw = data.get("jobs_results") or []
        jobs: list[JobItem] = []
        for item in raw[: max(1, limit)]:
            title = (item.get("title") or "").strip()
            company = (item.get("company_name") or "").strip()
            loc = item.get("location")
            if isinstance(loc, dict):
                location = (loc.get("display_name") or loc.get("name") or "").strip()
            else:
                location = (str(loc) if loc else "").strip()
            if not location:
                location = city
            link = (item.get("link") or "").strip()
            posted = ""
            ext = item.get("detected_extensions")
            if isinstance(ext, dict):
                posted = (str(ext.get("posted_at") or "")).strip()
            job: JobItem = {
                "title": title,
                "company": company,
                "location": location or city,
                "link": link or "#",
                "published": posted,
                "source": "google_jobs",
            }
            jobs.append(job)
        return jobs[:limit]
