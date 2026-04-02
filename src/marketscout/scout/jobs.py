"""Jobs Scout: fetch job-related signals from RSS. Live only; no sample fallback at runtime."""

from __future__ import annotations

from typing import Any

from marketscout.scout.errors import ScoutError
from marketscout.scout.providers import AdzunaProvider, RssJobsProvider

DEFAULT_JOBS_LIMIT = 10


def _normalize_job(item: dict[str, Any]) -> dict[str, str]:
    """Normalize a raw job dict to the canonical JobItem shape.

    Ensures all six fields (title, company, location, link, published, source)
    are present as stripped strings, with ``link`` defaulting to ``"#"`` when absent.
    """
    return {
        "title": (item.get("title") or "").strip(),
        "company": (item.get("company") or "").strip(),
        "location": (item.get("location") or "").strip(),
        "link": (item.get("link") or "").strip() or "#",
        "published": (item.get("published") or "").strip(),
        "source": (item.get("source") or "").strip(),
    }


def fetch_jobs(
    city: str | None = None,
    industry: str | None = None,
    limit: int = DEFAULT_JOBS_LIMIT,
    provider: str = "adzuna",
    allow_fallback: bool = False,
) -> list[dict[str, str]]:
    """
    Fetch job listings using a pluggable provider (default: Adzuna).

    Args:
        city: Target city (used for provider queries).
        industry: Target industry / keyword.
        limit: Max number of jobs to return.
        provider: Which provider to use: "adzuna" (default) or "rss".
        allow_fallback: If True and the primary provider fails, fall back to RSS provider.

    Raises:
        ScoutError: On provider failure or unknown provider.
    """
    city = (city or "Vancouver").strip()
    industry = (industry or "construction").strip()
    provider_key = (provider or "adzuna").strip().lower()

    if provider_key == "rss":
        rss = RssJobsProvider()
        return rss.fetch_jobs(city=city, industry=industry, limit=limit)

    if provider_key != "adzuna":
        raise ScoutError(
            f"Unknown jobs provider '{provider_key}'. "
            "Supported providers are: 'adzuna', 'rss'."
        )

    primary_error: Exception | None = None
    try:
        adzuna = AdzunaProvider()
        return adzuna.fetch_jobs(city=city, industry=industry, limit=limit)
    except ScoutError as e:
        primary_error = e

    if allow_fallback:
        try:
            rss = RssJobsProvider()
            return rss.fetch_jobs(city=city, industry=industry, limit=limit)
        except ScoutError:
            pass

    raise ScoutError(str(primary_error) if primary_error is not None else "Jobs provider failed.")
