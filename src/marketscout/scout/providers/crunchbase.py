"""Crunchbase Basic API: recently announced funding rounds (additive signals).

Uses ``CRUNCHBASE_KEY`` (user key). Returns an empty list if the key is unset or the
request fails — this module is optional enrichment and must not break the pipeline.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import requests

from marketscout.config import get_crunchbase_key

CRUNCHBASE_FUNDING_SEARCH_URL = (
    "https://api.crunchbase.com/v4/data/searches/funding_rounds"
)
REQUEST_TIMEOUT = 20


def _format_money(val: Any) -> str:
    if val is None:
        return ""
    if isinstance(val, dict):
        usd = val.get("value_usd")
        if usd is not None:
            return str(usd)
        return (val.get("value") or val.get("currency") or "").strip()
    return str(val).strip()


def _permalink(ident: Any) -> str:
    if isinstance(ident, dict):
        return (ident.get("permalink") or "").strip()
    return ""


def _display_value(ident: Any) -> str:
    if isinstance(ident, dict):
        return (ident.get("value") or ident.get("permalink") or "").strip()
    return ""


def fetch_funding_signals(
    city: str | None = None,
    industry: str | None = None,
    limit: int = 10,
) -> list[dict[str, str]]:
    """
    Fetch recently announced funding rounds and normalize into signal dicts.

    Each item: company, funding_round, amount, url, source=crunchbase.

    Filtering by ``industry`` is applied client-side on organization text when possible.
    """
    api_key = get_crunchbase_key()
    if not api_key:
        return []

    _ = city

    industry_kw = (industry or "").strip().lower()
    limit = max(1, min(limit, 50))

    since = (datetime.now(timezone.utc) - timedelta(days=180)).strftime("%Y-%m-%d")

    payload: dict[str, Any] = {
        "field_ids": [
            "identifier",
            "announced_on",
            "money_raised",
            "investment_stage",
            "funded_organization_identifier",
        ],
        "query": [
            {
                "type": "predicate",
                "field_id": "announced_on",
                "operator": "gte",
                "values": [since],
            },
        ],
        "order": [{"field_id": "announced_on", "sort": "desc"}],
        "limit": min(limit * 5, 50),
    }

    headers = {
        "Content-Type": "application/json",
        "X-cb-user-key": api_key,
        "accept": "application/json",
    }

    try:
        resp = requests.post(
            CRUNCHBASE_FUNDING_SEARCH_URL,
            json=payload,
            headers=headers,
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError):
        return []

    entities = data.get("entities") or []
    out: list[dict[str, str]] = []

    for ent in entities:
        if len(out) >= limit:
            break
        props = ent.get("properties") or {}
        org_ident = props.get("funded_organization_identifier")
        company = _display_value(org_ident)
        org_slug = _permalink(org_ident)

        stage_raw = props.get("investment_stage")
        if isinstance(stage_raw, dict):
            funding_round = (
                stage_raw.get("value") or stage_raw.get("permalink") or ""
            ).strip()
        else:
            funding_round = (str(stage_raw) if stage_raw else "").strip()

        amount = _format_money(props.get("money_raised"))

        fr_slug = _permalink(props.get("identifier"))
        if org_slug:
            url = f"https://www.crunchbase.com/organization/{org_slug}"
        elif fr_slug:
            url = f"https://www.crunchbase.com/funding_round/{fr_slug}"
        else:
            url = "https://www.crunchbase.com/discover/funding_rounds"

        haystack = f"{company} {funding_round}".lower()
        if industry_kw and industry_kw not in haystack:
            continue

        if not company:
            continue

        out.append({
            "company": company,
            "funding_round": funding_round or "unknown",
            "amount": amount,
            "url": url,
            "source": "crunchbase",
        })

    return out[:limit]
