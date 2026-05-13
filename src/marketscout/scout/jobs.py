"""Jobs Scout: fetch job-related signals from SerpAPI, Adzuna, or RSS (live only)."""

from __future__ import annotations

import logging
from typing import Any

from marketscout.config import get_serpapi_key
from marketscout.scout.errors import ScoutError
from marketscout.scout.providers import (
    AdzunaProvider,
    RssJobsProvider,
    SerpApiJobsProvider,
)

logger = logging.getLogger(__name__)

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


def _fetch_jobs_auto(
    city: str,
    industry: str,
    limit: int,
) -> list[dict[str, str]]:
    """SerpAPI (if key) → Adzuna (if configured) → RSS."""
    if get_serpapi_key():
        try:
            serp = SerpApiJobsProvider()
            provider_name = "serpapi"
            logger.info("Jobs provider: %s", provider_name)
            return serp.fetch_jobs(city=city, industry=industry, limit=limit)
        except ScoutError:
            pass

    primary_error: Exception | None = None
    try:
        adzuna = AdzunaProvider()
        provider_name = "adzuna"
        logger.info("Jobs provider: %s", provider_name)
        return adzuna.fetch_jobs(city=city, industry=industry, limit=limit)
    except ScoutError as e:
        primary_error = e

    try:
        rss = RssJobsProvider()
        provider_name = "rss"
        logger.info("Jobs provider: %s", provider_name)
        return rss.fetch_jobs(city=city, industry=industry, limit=limit)
    except ScoutError:
        pass

    raise ScoutError(str(primary_error) if primary_error is not None else "Jobs provider failed.")


def fetch_jobs(
    city: str | None = None,
    industry: str | None = None,
    limit: int = DEFAULT_JOBS_LIMIT,
    provider: str = "auto",
    allow_fallback: bool = False,
) -> list[dict[str, str]]:
    """
    Fetch job listings using a pluggable provider (default: auto chain).

    Args:
        city: Target city (used for provider queries).
        industry: Target industry / keyword.
        limit: Max number of jobs to return.
        provider: ``auto`` (SerpAPI if ``SERPAPI_KEY``, else Adzuna if configured,
            else RSS), ``serpapi``, ``adzuna``, or ``rss``.
        allow_fallback: For ``adzuna`` only: if True, fall back to RSS when Adzuna fails.
            Ignored when ``provider`` is ``auto`` (RSS is always the last resort).

    Raises:
        ScoutError: On provider failure or unknown provider.
    """
    city = (city or "Vancouver").strip()
    industry = (industry or "construction").strip()
    provider_key = (provider or "auto").strip().lower()

    if provider_key == "rss":
        rss = RssJobsProvider()
        provider_name = "rss"
        logger.info("Jobs provider: %s", provider_name)
        return rss.fetch_jobs(city=city, industry=industry, limit=limit)

    if provider_key == "serpapi":
        serp = SerpApiJobsProvider()
        provider_name = "serpapi"
        logger.info("Jobs provider: %s", provider_name)
        return serp.fetch_jobs(city=city, industry=industry, limit=limit)

    if provider_key == "auto":
        return _fetch_jobs_auto(city=city, industry=industry, limit=limit)

    if provider_key != "adzuna":
        raise ScoutError(
            f"Unknown jobs provider '{provider_key}'. "
            "Supported providers are: 'auto', 'serpapi', 'adzuna', 'rss'."
        )

    primary_error: Exception | None = None
    try:
        adzuna = AdzunaProvider()
        provider_name = "adzuna"
        logger.info("Jobs provider: %s", provider_name)
        return adzuna.fetch_jobs(city=city, industry=industry, limit=limit)
    except ScoutError as e:
        primary_error = e

    if allow_fallback:
        try:
            rss = RssJobsProvider()
            provider_name = "rss"
            logger.info("Jobs provider: %s", provider_name)
            return rss.fetch_jobs(city=city, industry=industry, limit=limit)
        except ScoutError:
            pass

    raise ScoutError(str(primary_error) if primary_error is not None else "Jobs provider failed.")
