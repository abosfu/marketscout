"""NewsAPI.org headline fetcher (everything search).

Uses ``NEWSAPI_KEY`` from the environment. Intended as a primary source when the key
is set; callers fall back to RSS on failure or missing key.
"""

from __future__ import annotations

import logging
from typing import Any

import requests

from marketscout.config import get_default_city, get_max_headlines
from marketscout.scout.errors import ScoutError

logger = logging.getLogger(__name__)

NEWSAPI_EVERYTHING_URL = "https://newsapi.org/v2/everything"
REQUEST_TIMEOUT = 15

# Default request volume — match the jobs pipeline so we surface comparable
# company mention coverage from news.
DEFAULT_LIMIT = 50


def fetch_news_headlines(
    city: str | None = None,
    industry: str | None = None,
    limit: int | None = None,
    api_key: str | None = None,
) -> list[dict[str, str]]:
    """
    Fetch headlines from NewsAPI ``/v2/everything``.

    Returns dicts aligned with RSS headline shape: title, source, link, published
    (source field is ``newsapi`` per product convention).
    """
    from marketscout.config import get_newsapi_key

    key = (api_key or get_newsapi_key()).strip()
    if not key:
        raise ScoutError("NewsAPI requires NEWSAPI_KEY in the environment.")

    city = (city or get_default_city()).strip() or "Vancouver"
    industry = (industry or "").strip()
    if limit is None:
        max_default = get_max_headlines()
        # Prefer the larger of the configured default and our 50-headline floor
        # so the company-mention coverage stays high even when callers omit limit.
        limit = max(max_default, DEFAULT_LIMIT)
    limit = max(1, min(limit, 100))

    def _fetch(q: str) -> tuple[list[dict[str, str]], dict[str, Any]]:
        """Execute one NewsAPI request and return (articles_list, raw_json)."""
        params: dict[str, Any] = {
            "q": q,
            "language": "en",
            "sortBy": "relevancy",
            "searchIn": "title,description",
            "pageSize": limit,
            "apiKey": key,
        }
        try:
            resp = requests.get(
                NEWSAPI_EVERYTHING_URL, params=params, timeout=REQUEST_TIMEOUT
            )
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as e:
            raise ScoutError(f"NewsAPI request failed: {e}") from e
        except ValueError as e:
            raise ScoutError(f"NewsAPI response was not valid JSON: {e}") from e

        status = (data.get("status") or "").strip().lower()
        if status != "ok":
            msg = (data.get("message") or data.get("code") or "unknown error").strip()
            raise ScoutError(f"NewsAPI error: {msg}")

        return data.get("articles") or [], data

    # Primary query: exact phrase match for both city and industry term.
    # This ensures articles mention the specific industry in context, not just
    # any Vancouver news that happens to share a generic keyword.
    q_primary = f'"{city}" "{industry}"' if industry else f'"{city}"'
    articles, _ = _fetch(q_primary)

    # Fallback: broader AND query when the tight phrase match yields too few results.
    q_used = q_primary
    if len(articles) < 3 and industry:
        q_fallback = f'"{city}" AND {industry}'
        articles_fb, _ = _fetch(q_fallback)
        if articles_fb:
            articles = articles_fb
            q_used = q_fallback

    out: list[dict[str, str]] = []
    for article in articles[:limit]:
        title = (article.get("title") or "").strip()
        url = (article.get("url") or "").strip()
        pub = (article.get("publishedAt") or "").strip()
        if not title:
            continue
        out.append({
            "title": title,
            "source": "newsapi",
            "link": url or "#",
            "published": pub,
        })

    logger.info(
        "NewsAPI /everything query=%r requested=%d returned=%d",
        q_used,
        limit,
        len(out),
    )
    return out
