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

from datetime import datetime
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import marketscout.config  # noqa: F401 — triggers load_dotenv() at server startup
from marketscout.backend.nl2sql import router as nl2sql_router

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


class EmailRequest(BaseModel):
    run_id: int
    opportunities: list[Any] = []
    city: str
    industry: str


# ── Internal pipeline helper (isolated for test patching) ────────────────────

def _execute_search_pipeline(
    city: str, industry: str, limit: int
) -> tuple[int, list[dict], int]:
    """
    Run the full Bronze → Silver → Gold pipeline for one search request.

    Returns:
        (run_id, opportunity_dicts, signal_count)

    Isolated into its own function so tests can monkeypatch
    ``marketscout.backend.main._execute_search_pipeline`` without touching
    network calls or the database.
    """
    from marketscout.backend.ai import generate_strategy
    from marketscout.config import get_db_path
    from marketscout.db import init_db, write_gold
    from marketscout.scout import fetch_headlines, fetch_jobs

    run_id = int(datetime.utcnow().timestamp())
    headlines = fetch_headlines(city=city, industry=industry, limit=limit)
    jobs = fetch_jobs(city=city, industry=industry, limit=limit)
    strategy = generate_strategy(headlines, industry=industry, city=city, jobs=jobs)
    db_path = get_db_path()
    init_db(db_path)
    write_gold(
        str(run_id),
        city,
        industry,
        strategy.opportunity_map,
        headlines + jobs,
        db_path=db_path,
    )
    return run_id, strategy.to_json_dict()["opportunity_map"], len(headlines) + len(jobs)


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
        run_id, opportunities, signal_count = _execute_search_pipeline(
            body.city, body.industry, body.limit
        )
        return {
            "run_id": run_id,
            "opportunities": opportunities,
            "signal_count": signal_count,
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
    from marketscout.config import get_db_path, get_google_api_key

    db_path = get_db_path()
    if not db_path.exists():
        raise HTTPException(
            status_code=503,
            detail="Run a search first to populate the database.",
        )

    api_key = get_google_api_key()
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail=(
                "GOOGLE_API_KEY is not configured. "
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


@app.post("/email")
def email_briefing(body: EmailRequest) -> dict:
    """
    Send a plain-text briefing email summarising the opportunity map for a run.

    Returns {"sent": bool, "detail": str}.  Never raises — SMTP failures and
    missing config are surfaced in the response body.
    """
    from marketscout.backend.email_sender import send_briefing

    sent, detail = send_briefing(body.model_dump())
    return {"sent": sent, "detail": detail}
