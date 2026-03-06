"""Adzuna jobs provider: real job listings via Adzuna Jobs API."""

from __future__ import annotations

import os
from typing import Any

import requests

from marketscout.scout.errors import ScoutError

from .base import JobItem, JobsProvider

ADZUNA_BASE_URL = "https://api.adzuna.com/v1/api/jobs"
REQUEST_TIMEOUT = 10


def _get_env(name: str) -> str:
    """Read and strip an environment variable; return empty string if missing."""
    return os.environ.get(name, "").strip()


class AdzunaProvider(JobsProvider):
    """JobsProvider implementation backed by the Adzuna Jobs API."""

    def __init__(
        self,
        app_id: str | None = None,
        app_key: str | None = None,
        country: str | None = None,
    ) -> None:
        self.app_id = (app_id or _get_env("ADZUNA_APP_ID")).strip()
        self.app_key = (app_key or _get_env("ADZUNA_APP_KEY")).strip()
        # Default to Canada (ca) if not provided
        self.country = (country or _get_env("ADZUNA_COUNTRY") or "ca").lower()

        if not self.app_id or not self.app_key:
            raise ScoutError(
                "Adzuna provider requires ADZUNA_APP_ID and ADZUNA_APP_KEY environment variables. "
                "Set them in your environment, or run with --jobs-provider=rss or --allow-provider-fallback "
                "to use the RSS jobs provider instead."
            )

    def fetch_jobs(self, city: str, industry: str, limit: int) -> list[JobItem]:
        """
        Fetch job listings from Adzuna for the given city and industry.

        Returns a list of normalized JobItem dicts:
        {title, company, location, link, published, source}.
        """
        city = (city or "").strip()
        industry = (industry or "").strip()
        # Adzuna search endpoint: /v1/api/jobs/{country}/search/{page}
        url = f"{ADZUNA_BASE_URL}/{self.country}/search/1"
        params: dict[str, Any] = {
            "app_id": self.app_id,
            "app_key": self.app_key,
            "results_per_page": max(1, min(limit, 50)),
        }
        if industry:
            params["what"] = industry
        if city:
            params["where"] = city

        try:
            resp = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as e:
            raise ScoutError(f"Adzuna jobs request failed: {e}") from e
        except ValueError as e:
            # JSON decode error
            raise ScoutError(f"Adzuna jobs response was not valid JSON: {e}") from e

        results = data.get("results") or []
        jobs: list[JobItem] = []
        for item in results[:limit]:
            title = (item.get("title") or "").strip()
            company_obj = item.get("company") or {}
            location_obj = item.get("location") or {}
            company_name = (company_obj.get("display_name") or "").strip()
            location_name = (location_obj.get("display_name") or city).strip()
            link = (item.get("redirect_url") or "").strip()
            created = (item.get("created") or "").strip()
            job: JobItem = {
                "title": title,
                "company": company_name,
                "location": location_name,
                "link": link or "#",
                "published": created,
                "source": "adzuna",
            }
            jobs.append(job)
        return jobs

