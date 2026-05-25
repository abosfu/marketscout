"""NL2SQL router: translate natural-language questions into SQL queries and insights.

GROQ_API_KEY is resolved from the environment at request time (populated by
config.load_dotenv() which runs when the marketscout.config module is first imported).
The database path is resolved via get_db_path() — the live SQLite file written by
`marketscout run`. There is no sample/mock fallback in this module.

Pipeline (per request):
  1. Build schema context from read-only SQLite + Gold-layer hints
  2. User question → Groq chat completion (llama-3.1-8b-instant) → SQL text
  3. Safety check: reject DROP / DELETE / UPDATE / INSERT
  4. Execute SQL against a READ-ONLY SQLite connection
  5. Second Groq call: raw rows → plain-English business insight

Groq calls run inside ``ThreadPoolExecutor`` with a hard timeout so hung HTTP
requests cannot block the server indefinitely. All Groq failures surface as
HTTP 503 with ``Groq API unavailable — check GROQ_API_KEY``.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()

# Keywords that must never appear in AI-generated SQL.
_UNSAFE_KEYWORDS: frozenset[str] = frozenset({"DROP", "DELETE", "UPDATE", "INSERT"})

# Extra schema context for the LLM (dim_signals company-level fields).
_GOLD_SCHEMA_HINT = """
MarketScout Gold layer (SQLite) — use these tables for company and hiring questions:

dim_signals — one row per raw headline or job posting captured in a run:
  - id, run_id, source, title, summary, url, captured_at, content_hash
  - company_name (TEXT, nullable): employer from job postings; NULL for news-only rows
  - signal_type (TEXT): 'job' for job listings (google_jobs, adzuna sources), 'news' for headlines

dim_opportunities — scored opportunity categories per run (company, total_score, rank, …)
dim_runs — run metadata (id, city, industry, signal_count, …)
fact_leads — links opportunities to supporting signals

For questions like "What is [Company] hiring for?" query dim_signals WHERE
signal_type = 'job' AND company_name LIKE '%Company%' (case-insensitive) and return title.
For news about a company, use signal_type = 'news' and filter title or company_name.
Always filter by the latest run_id when the user refers to the current search.
"""

_GROQ_MODEL = "llama-3.1-8b-instant"
_GROQ_TIMEOUT_SEC = 20.0
_GROQ_UNAVAILABLE_MSG = "Groq API unavailable — check GROQ_API_KEY"


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


def _sqlite_schema_context(db_path: str) -> str:
    """DDL + small samples from the read-only Gold DB for the SQL-generation prompt."""
    path = str(Path(db_path).resolve())
    uri = f"file:{path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
        chunks: list[str] = []
        for (tname,) in tables:
            row = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
                (tname,),
            ).fetchone()
            if row and row[0]:
                chunks.append(row[0] + ";")
            try:
                cur = conn.execute(f'SELECT * FROM "{tname}" LIMIT 3')
                cols = [d[0] for d in cur.description] if cur.description else []
                samples = cur.fetchall()
                chunks.append(
                    f"-- Sample rows for {tname} (columns={cols}): {samples!r}"
                )
            except sqlite3.Error:
                pass
        return "\n\n".join(chunks) if chunks else "(empty database)"
    finally:
        conn.close()


def _extract_sql_from_model_output(raw: str) -> str:
    """Pull a single SQL statement from model output (strip markdown fences)."""
    text = raw.strip()
    m = re.search(r"```(?:sql)?\s*([\s\S]*?)```", text, re.IGNORECASE)
    if m:
        text = m.group(1).strip()
    # Drop leading comment-only lines
    lines_out: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("--"):
            continue
        lines_out.append(line)
    return "\n".join(lines_out).strip()


def _groq_generate_blocking(prompt: str, api_key: str) -> str:
    """Synchronous Groq chat completion (runs inside executor worker thread)."""
    from groq import Groq

    client = Groq(api_key=api_key)
    response = client.chat.completions.create(
        model=_GROQ_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.0,
    )
    try:
        text = (response.choices[0].message.content or "").strip()
    except (AttributeError, IndexError, TypeError):
        text = ""
    if not text:
        raise ValueError("Empty or blocked Groq response")
    return text


def _groq_generate(prompt: str, api_key: str) -> str:
    """Call Groq with a hard wall-clock timeout (never blocks past ``_GROQ_TIMEOUT_SEC``)."""
    try:
        with ThreadPoolExecutor(max_workers=1) as ex:
            fut = ex.submit(_groq_generate_blocking, prompt, api_key)
            return fut.result(timeout=_GROQ_TIMEOUT_SEC)
    except FutureTimeoutError as exc:
        raise HTTPException(
            status_code=503,
            detail=_GROQ_UNAVAILABLE_MSG,
        ) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=_GROQ_UNAVAILABLE_MSG,
        ) from exc


def _run_readonly_sql(db_path: str, sql: str) -> str:
    """Execute read-only SELECT and return JSON-serialised preview."""
    path = str(Path(db_path).resolve())
    uri = f"file:{path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        cur = conn.execute(sql)
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description] if cur.description else []
        preview = rows[:500]
        return json.dumps(
            {"columns": cols, "row_count": len(rows), "rows": preview},
            default=str,
        )
    finally:
        conn.close()


def _run_nl2sql_pipeline(question: str, db_path: str, api_key: str) -> tuple[str, str]:
    """
    Core NL2SQL pipeline. Isolated into its own function so tests can
    monkeypatch `marketscout.backend.nl2sql._run_nl2sql_pipeline` without
    needing the groq SDK installed.

    Returns:
        (sql_query, insights) — both are non-empty strings.
    """
    schema_ctx = _sqlite_schema_context(db_path)

    sql_prompt = (
        "You are an expert SQLite analyst for MarketScout. "
        "Answer the user with exactly one read-only query.\n\n"
        "Rules:\n"
        "- Output a single SELECT (or WITH … SELECT) statement only.\n"
        "- Valid SQLite 3 syntax. You may use LIKE, LIMIT, ORDER BY.\n"
        "- Optionally wrap the SQL in a ```sql fenced code block; otherwise plain SQL only.\n"
        "- No explanation, no commentary outside the query.\n\n"
        f"--- DATABASE SCHEMA ---\n{schema_ctx}\n\n"
        f"{_GOLD_SCHEMA_HINT.strip()}\n\n"
        f"User question: {question.strip()}\n"
    )

    sql_raw = _groq_generate(sql_prompt, api_key)
    sql_query = _extract_sql_from_model_output(sql_raw)
    if not sql_query:
        raise HTTPException(
            status_code=503,
            detail=_GROQ_UNAVAILABLE_MSG,
        )

    _check_safety(sql_query)

    try:
        raw_results = _run_readonly_sql(db_path, sql_query)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"SQL execution failed: {exc}",
        ) from exc

    synthesis_prompt = (
        f"Original question: {question}\n\n"
        f"SQL query used: {sql_query}\n\n"
        f"Raw query results (JSON): {raw_results}\n\n"
        "Synthesize these data rows into a clear, one-paragraph business insight "
        "for a product manager. Focus on what the numbers mean, not how they were retrieved."
    )
    insights = _groq_generate(synthesis_prompt, api_key)
    return sql_query, insights


# ── Route ─────────────────────────────────────────────────────────────────────

@router.post("/ask", response_model=QueryResponse)
def ask(request: QueryRequest) -> QueryResponse:
    """
    Accept a natural-language question, run the NL2SQL pipeline, and return
    the generated SQL query together with a plain-English business insight.

    Requires the GROQ_API_KEY environment variable.
    The target database must exist (run `marketscout run` first).
    """
    # ── pre-flight checks ────────────────────────────────────────────────────
    api_key = os.environ.get("GROQ_API_KEY", "").strip()
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail=(
                "GROQ_API_KEY is not configured. "
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
