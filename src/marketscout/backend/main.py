"""MarketScout FastAPI application.

Endpoints:
  GET  /          — health check
  POST /search    — run full pipeline and return scored opportunities
  POST /ask       — NL2SQL query against the Gold layer database
  POST /email     — send a plain-text briefing via Gmail SMTP

The legacy /api/ask route (nl2sql router) is preserved for backward compatibility.
All three feature endpoints live directly in this file — no router splitting.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import marketscout.config  # noqa: F401 — triggers load_dotenv() at server startup
from marketscout.backend.nl2sql import router as nl2sql_router

logger = logging.getLogger(__name__)

app = FastAPI(
    title="MarketScout API",
    version="2.0",
    description="API layer for MarketScout opportunity mapping and NL2SQL queries.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Legacy route — preserved so existing tests and integrations continue to work.
app.include_router(nl2sql_router, prefix="/api")


# ── Request / Response models ─────────────────────────────────────────────────

class SearchRequest(BaseModel):
    city: str
    industry: str
    limit: int = 50


class AskRequest(BaseModel):
    question: str
    run_id: int



# ── Internal pipeline helper (isolated for test patching) ────────────────────

def _normalize_signals_for_gold(
    headlines: list[dict[str, Any]],
    jobs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Ensure each signal dict has company, source, and run_id for Gold layer writes."""
    out: list[dict[str, Any]] = []
    for h in headlines:
        sig = dict(h)
        sig["company"] = (sig.get("company") or "").strip()
        sig["source"] = (sig.get("source") or "newsapi").strip()
        out.append(sig)
    for j in jobs:
        sig = dict(j)
        sig["company"] = (sig.get("company") or "").strip()
        sig["source"] = (sig.get("source") or "").strip()
        out.append(sig)
    return out


def _dedupe_jobs_title_company(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop exact duplicates by (title, company), case-insensitive. Keeps first occurrence."""
    seen: set[tuple[str, str]] = set()
    out: list[dict[str, Any]] = []
    for j in jobs:
        if not isinstance(j, dict):
            continue
        title = (j.get("title") or "").strip().lower()
        company = (j.get("company") or "").strip().lower()
        if not title and not company:
            out.append(j)
            continue
        key = (title, company)
        if key in seen:
            continue
        seen.add(key)
        out.append(j)
    return out


def _dedupe_jobs_by_company(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep the first job per non-empty company name (case-insensitive).

    Jobs without a company name are kept individually so we don't drop blanks
    that may still contribute to opportunity scoring via title-keyword matches.
    """
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for j in jobs:
        if not isinstance(j, dict):
            continue
        company = (j.get("company") or "").strip()
        if not company:
            out.append(j)
            continue
        key = company.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(j)
    return out


def _fetch_jobs_dual_query(
    city: str, industry: str, per_query_limit: int
) -> list[dict[str, Any]]:
    """
    When SerpAPI is configured, fetch jobs via TWO queries and combine.

        Query 1: ``"{industry} jobs {city}"``  (canonical)
        Query 2: ``"{industry} hiring {city}"`` (boosts intent-signal coverage)

    Results are combined and deduplicated by (title, company). When SerpAPI is
    not configured (no ``SERPAPI_KEY``) we fall back to the existing ``fetch_jobs``
    auto chain (Adzuna → RSS) for a single query, preserving prior behaviour.
    """
    from marketscout.config import get_serpapi_key
    from marketscout.scout import fetch_jobs
    from marketscout.scout.errors import ScoutError
    from marketscout.scout.providers import SerpApiJobsProvider

    if get_serpapi_key():
        try:
            provider = SerpApiJobsProvider()
            city_q = (city or "").strip()
            industry_q = (industry or "").strip()
            q1 = f"{industry_q} jobs {city_q}".strip() or "jobs"
            q2 = f"{industry_q} hiring {city_q}".strip() or "hiring"
            jobs_q1 = provider.fetch_jobs(
                city=city, industry=industry, limit=per_query_limit, query=q1
            )
            jobs_q2 = provider.fetch_jobs(
                city=city, industry=industry, limit=per_query_limit, query=q2
            )
            combined = list(jobs_q1) + list(jobs_q2)
            deduped = _dedupe_jobs_title_company(combined)
            logger.info(
                "SerpAPI dual-query: q1=%d q2=%d combined=%d after_title_company_dedupe=%d",
                len(jobs_q1),
                len(jobs_q2),
                len(combined),
                len(deduped),
            )
            return deduped
        except ScoutError as exc:
            logger.warning(
                "SerpAPI dual-query failed (%s); falling back to fetch_jobs auto chain",
                exc,
            )

    return fetch_jobs(city=city, industry=industry, limit=per_query_limit)


def _execute_search_pipeline(
    city: str, industry: str, limit: int
) -> tuple[int, list[dict], int, list[dict[str, Any]], list[dict[str, Any]]]:
    """
    Run the full Bronze → Silver → Gold pipeline for one search request.

    Returns:
        (run_id, opportunity_dicts, signal_count, jobs, headlines)

    Isolated into its own function so tests can monkeypatch
    ``marketscout.backend.main._execute_search_pipeline`` without touching
    network calls or the database.

    Headlines and jobs are each fetched with a fixed volume (50) so more
    signals are available for keyword coverage; ``limit`` remains on the
    request model for API compatibility.

    Every job and headline dict is stamped with the current ``run_id`` before
    being persisted or returned to the caller. The Gold layer (``dim_signals``)
    is already scoped per-run via its ``run_id`` FK, but stamping the in-memory
    dicts means the API response is provably run-scoped too — the frontend can
    safely treat ``current_run["jobs"]`` / ``current_run["headlines"]`` as
    belonging to exactly one search.
    """
    from marketscout.backend.ai import generate_strategy
    from marketscout.config import get_db_path
    from marketscout.db import init_db, write_gold
    from marketscout.scout import fetch_headlines

    _ = limit  # reserved for API; fetch volume fixed below
    headlines_fetch_limit = 50
    jobs_per_query_limit = 50  # SerpAPI dual-query → up to 100 raw jobs before dedupe

    run_id = int(datetime.utcnow().timestamp())
    headlines = fetch_headlines(
        city=city, industry=industry, limit=headlines_fetch_limit
    )
    jobs = _fetch_jobs_dual_query(
        city=city, industry=industry, per_query_limit=jobs_per_query_limit
    )

    # Company-level dedupe — keep the first job per company so the table
    # surfaces unique companies, not the same employer repeated across roles.
    jobs = _dedupe_jobs_by_company(jobs)
    unique_companies = {
        (j.get("company") or "").strip().lower()
        for j in jobs
        if (j.get("company") or "").strip()
    }
    logger.info(
        "Search pipeline: %d jobs after dedupe, %d unique companies, %d headlines",
        len(jobs),
        len(unique_companies),
        len(headlines),
    )

    # Tag every raw signal with the current run_id so downstream consumers
    # (Gold layer + frontend) can filter cleanly and never bleed across runs.
    for j in jobs:
        if isinstance(j, dict):
            j["run_id"] = run_id
    for h in headlines:
        if isinstance(h, dict):
            h["run_id"] = run_id

    strategy = generate_strategy(headlines, industry=industry, city=city, jobs=jobs)
    signals = _normalize_signals_for_gold(headlines, jobs)
    db_path = get_db_path()
    init_db(db_path)
    write_gold(
        str(run_id),
        city,
        industry,
        strategy.opportunity_map,
        signals,
        db_path=db_path,
    )
    return (
        run_id,
        strategy.to_json_dict()["opportunity_map"],
        len(signals),
        jobs,
        headlines,
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/")
def root() -> dict[str, str]:
    return {"status": "MarketScout API is running", "version": "2.0"}


@app.post("/search")
def search(body: SearchRequest) -> dict:
    """
    Run the full pipeline for the given city + industry and return scored opportunities.

    Generates a run_id from the current UTC timestamp, fetches live signals,
    scores them, persists to the Gold layer, and returns the opportunity map.
    Returns HTTP 500 with {"detail": str(e)} on any pipeline failure.
    """
    try:
        run_id, opportunities, signal_count, jobs, headlines = _execute_search_pipeline(
            body.city, body.industry, body.limit
        )
        return {
            "run_id": run_id,
            "opportunities": opportunities,
            "signal_count": signal_count,
            "jobs": jobs,
            "headlines": headlines,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/ask")
def ask_nl2sql(body: AskRequest) -> dict:
    """
    Translate a natural-language question into SQL, execute it against the Gold
    layer, and return a plain-English business insight.

    Gates on the database file existing — returns HTTP 503 if the Gold layer has
    not been populated yet (run /search first).
    """
    from marketscout.backend.nl2sql import _run_nl2sql_pipeline
    from marketscout.config import get_db_path, get_groq_key

    db_path = get_db_path()
    if not db_path.exists():
        raise HTTPException(
            status_code=503,
            detail="Run a search first to populate the database.",
        )

    api_key = get_groq_key()
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail=(
                "GROQ_API_KEY is not configured. "
                "Set the environment variable to enable NL2SQL."
            ),
        )

    try:
        sql_query, insights = _run_nl2sql_pipeline(
            question=body.question,
            db_path=str(db_path),
            api_key=api_key,
        )
        return {"sql_query": sql_query, "insights": insights}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


