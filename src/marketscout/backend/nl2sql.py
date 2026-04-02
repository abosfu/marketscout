"""NL2SQL router: translate natural-language questions into SQL queries and insights.

GOOGLE_API_KEY is resolved from the environment at request time (populated by
config.load_dotenv() which runs when the marketscout.config module is first imported).
The database path is resolved via get_db_path() — the live SQLite file written by
`marketscout run`. There is no sample/mock fallback in this module.


Pipeline (per request):
  1. User question → LangChain create_sql_query_chain → raw SQL
  2. Safety check: reject DROP / DELETE / UPDATE / INSERT
  3. Execute SQL against a READ-ONLY SQLite connection
  4. Second Gemini call: raw rows → plain-English business insight
  5. Return { sql_query, insights }

All LangChain/Gemini imports are lazy (inside helper functions) so the module
loads cleanly in tests without the real packages being present.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()

# Keywords that must never appear in AI-generated SQL.
_UNSAFE_KEYWORDS: frozenset[str] = frozenset({"DROP", "DELETE", "UPDATE", "INSERT"})


# ── Pydantic models ───────────────────────────────────────────────────────────

class QueryRequest(BaseModel):
    """Payload for the POST /api/ask endpoint."""

    user_question: str


class QueryResponse(BaseModel):
    """Response returned by the POST /api/ask endpoint."""

    sql_query: str
    insights: str


# ── Helpers ───────────────────────────────────────────────────────────────────

def _check_safety(sql: str) -> None:
    """
    Raise HTTP 400 if the SQL contains any write or DDL keyword.
    Comparison is case-insensitive and checks whole-word boundaries are not
    required — any occurrence is treated as unsafe.
    """
    upper = sql.upper()
    for kw in _UNSAFE_KEYWORDS:
        if kw in upper:
            raise HTTPException(
                status_code=400,
                detail=f"Unsafe query detected: statement contains '{kw}'.",
            )


def _make_readonly_db(db_path: str):
    """
    Return a LangChain SQLDatabase backed by a READ-ONLY SQLite connection.
    Uses sqlite3's URI mode (?mode=ro) so the engine can never mutate data.
    sample_rows_in_table_info=3 gives the LLM concrete examples of the data
    shape without exposing the full table.
    """
    from sqlalchemy import create_engine
    from langchain_community.utilities import SQLDatabase

    def _creator() -> sqlite3.Connection:
        return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)

    engine = create_engine("sqlite://", creator=_creator)
    return SQLDatabase(engine, sample_rows_in_table_info=3)


def _run_nl2sql_pipeline(question: str, db_path: str, api_key: str) -> tuple[str, str]:
    """
    Core NL2SQL pipeline. Isolated into its own function so tests can
    monkeypatch `marketscout.backend.nl2sql._run_nl2sql_pipeline` without
    needing real LangChain/Gemini packages installed.

    Returns:
        (sql_query, insights) — both are non-empty strings.
    """
    from langchain.chains import create_sql_query_chain
    from langchain_core.messages import HumanMessage
    from langchain_google_genai import ChatGoogleGenerativeAI

    db = _make_readonly_db(db_path)
    llm = ChatGoogleGenerativeAI(
        model="gemini-1.5-pro-latest",
        google_api_key=api_key,
        temperature=0,
    )

    # Step 1 — generate SQL
    chain = create_sql_query_chain(llm, db)
    sql_query: str = chain.invoke({"question": question}).strip()

    # Step 2 — safety gate (raises HTTP 400 on violation)
    _check_safety(sql_query)

    # Step 3 — execute against the read-only database
    try:
        raw_results: str = db.run(sql_query)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"SQL execution failed: {exc}",
        ) from exc

    # Step 4 — synthesise a plain-English insight
    synthesis_prompt = (
        f"Original question: {question}\n\n"
        f"SQL query used: {sql_query}\n\n"
        f"Raw query results: {raw_results}\n\n"
        "Synthesize these data rows into a clear, one-paragraph business insight "
        "for a product manager. Focus on what the numbers mean, not how they were retrieved."
    )
    synthesis_response = llm.invoke([HumanMessage(content=synthesis_prompt)])
    insights: str = synthesis_response.content

    return sql_query, insights


# ── Route ─────────────────────────────────────────────────────────────────────

@router.post("/ask", response_model=QueryResponse)
def ask(request: QueryRequest) -> QueryResponse:
    """
    Accept a natural-language question, run the NL2SQL pipeline, and return
    the generated SQL query together with a plain-English business insight.

    Requires the GOOGLE_API_KEY environment variable.
    The target database must exist (run `marketscout run` first).
    """
    # ── pre-flight checks ────────────────────────────────────────────────────
    api_key = os.environ.get("GOOGLE_API_KEY", "").strip()
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail=(
                "GOOGLE_API_KEY is not configured. "
                "Set the environment variable to enable NL2SQL."
            ),
        )

    from marketscout.config import get_db_path as _get_db_path

    db_path_obj: Path = _get_db_path()
    if not db_path_obj.exists():
        raise HTTPException(
            status_code=500,
            detail=(
                f"Database not found at '{db_path_obj}'. "
                "Run 'marketscout run' at least once to populate the database."
            ),
        )
    db_path = str(db_path_obj)

    # ── pipeline ─────────────────────────────────────────────────────────────
    try:
        sql_query, insights = _run_nl2sql_pipeline(
            question=request.user_question,
            db_path=db_path,
            api_key=api_key,
        )
    except HTTPException:
        raise  # safety (400) and execution (500) errors propagate as-is
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"NL2SQL pipeline error: {exc}",
        ) from exc

    return QueryResponse(sql_query=sql_query, insights=insights)
