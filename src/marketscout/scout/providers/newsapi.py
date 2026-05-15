"""NewsAPI.org headline fetcher (everything search).

Uses ``NEWSAPI_KEY`` from the environment. Intended as a primary source when the key
is set; callers fall back to RSS on failure or missing key.
"""

from __future__ import annotations

from typing import Any

import requests

from marketscout.config import get_default_city, get_max_headlines
from marketscout.scout.errors import ScoutError

NEWSAPI_EVERYTHING_URL = "https://newsapi.org/v2/everything"
REQUEST_TIMEOUT = 15


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
    limit = limit if limit is not None else get_max_headlines()
    limit = max(1, min(limit, 100))

    # Target construction-specific news: require the city and at least one
    # construction-related term in the title or description.
    head = city
    q = (
        f'"{head}" AND '
        f'("{industry}" OR "building" OR "contractor" OR "housing" '
        f'OR "development" OR "permit" OR "renovation")'
    )

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

    articles = data.get("articles") or []
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
    return out
