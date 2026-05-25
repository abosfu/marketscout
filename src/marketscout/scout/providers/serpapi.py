"""SerpAPI Google Jobs provider via SerpApi ``engine=google_jobs``.

Requires ``SERPAPI_KEY`` (see ``marketscout.config.get_serpapi_key``).

Google Jobs returns ~10 results per page, paginated via ``serpapi_pagination.
next_page_token``. We page until we either hit ``limit`` results or run out of
pages (capped at ``MAX_PAGES`` to bound SerpAPI quota usage).
"""

from __future__ import annotations

import logging
from typing import Any

import requests

from marketscout.config import get_serpapi_key
from marketscout.scout.errors import ScoutError

from .base import JobItem, JobsProvider

logger = logging.getLogger(__name__)

SERPAPI_URL = "https://serpapi.com/search.json"
REQUEST_TIMEOUT = 15

# Default fetch volume — paginates up to ~5 pages × 10 results.
DEFAULT_LIMIT = 50
# Google Jobs returns ~10 results per page. Cap pages to keep quota bounded.
MAX_PAGES = 6


class SerpApiJobsProvider(JobsProvider):
    """JobsProvider backed by SerpAPI Google Jobs search."""

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = (api_key or get_serpapi_key()).strip()
        if not self.api_key:
            raise ScoutError(
                "SerpAPI jobs provider requires SERPAPI_KEY in the environment."
            )

    def fetch_jobs(
        self,
        city: str,
        industry: str,
        limit: int = DEFAULT_LIMIT,
        query: str | None = None,
    ) -> list[JobItem]:
        """Fetch up to ``limit`` jobs from Google Jobs via SerpAPI.

        Args:
            city:     Target city (also used as a location fallback per item).
            industry: Target industry, used to build the default query.
            limit:    Max jobs to return; pagination walks pages until we hit it.
            query:    Optional explicit search string. When ``None`` we fall back
                      to ``f"{industry} jobs {city}"`` to preserve existing behaviour.

        Returns:
            List of normalized JobItem dicts, deduped by link within this call.
        """
        city = (city or "").strip()
        industry = (industry or "").strip()
        limit = max(1, int(limit))
        q = (query or f"{industry} jobs {city}").strip() or "jobs"

        base_params: dict[str, Any] = {
            "engine": "google_jobs",
            "q": q,
            "api_key": self.api_key,
        }

        jobs: list[JobItem] = []
        seen_links: set[str] = set()
        next_token: str | None = None
        pages_fetched = 0
        first_call_error: ScoutError | None = None

        while len(jobs) < limit and pages_fetched < MAX_PAGES:
            params = dict(base_params)
            if next_token:
                params["next_page_token"] = next_token

            try:
                resp = requests.get(SERPAPI_URL, params=params, timeout=REQUEST_TIMEOUT)
                resp.raise_for_status()
                data = resp.json()
            except requests.RequestException as e:
                if pages_fetched == 0:
                    first_call_error = ScoutError(
                        f"SerpAPI Google Jobs request failed: {e}"
                    )
                break
            except ValueError as e:
                if pages_fetched == 0:
                    first_call_error = ScoutError(
                        f"SerpAPI Google Jobs response was not valid JSON: {e}"
                    )
                break

            err = (data.get("error") or "").strip()
            if err:
                if pages_fetched == 0:
                    first_call_error = ScoutError(f"SerpAPI Google Jobs error: {err}")
                break

            raw = data.get("jobs_results") or []
            if not raw:
                break

            for item in raw:
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
                if link and link in seen_links:
                    continue
                if link:
                    seen_links.add(link)
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
                if len(jobs) >= limit:
                    break

            pages_fetched += 1
            pagination = data.get("serpapi_pagination") or {}
            next_token = (pagination.get("next_page_token") or "").strip() or None
            if not next_token:
                break

        # Surface only the first-page failure — partial paginated results are fine.
        if not jobs and first_call_error is not None:
            raise first_call_error

        filled = sum(1 for j in jobs if (j.get("company") or "").strip())
        blanks = len(jobs) - filled
        logger.info(
            "SerpAPI google_jobs query=%r pages=%d total=%d company_filled=%d blank=%d",
            q,
            pages_fetched,
            len(jobs),
            filled,
            blanks,
        )

        return jobs[:limit]
