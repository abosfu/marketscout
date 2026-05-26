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
import logging
import os
import re
import sqlite3
import traceback
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from pathlib import Path

_log = logging.getLogger(__name__)

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()

# Keywords that must never appear in AI-generated SQL.
_UNSAFE_KEYWORDS: frozenset[str] = frozenset({"DROP", "DELETE", "UPDATE", "INSERT"})

# Extra schema context for the LLM (dim_signals company-level fields).
_GOLD_SCHEMA_HINT = """
MarketScout Gold layer (SQLite) — use these tables for company and hiring questions:

TABLE REFERENCE:
  dim_runs       — id (PK, TEXT), city, industry, signal_count  [id IS the run identifier]
  dim_signals    — id (PK), run_id (FK → dim_runs.id), source, title, summary, url,
                   captured_at, content_hash,
                   company_name (TEXT, nullable): employer name for job rows,
                   signal_type (TEXT): 'job' (Google Jobs/Adzuna) OR 'news' (headlines)
  dim_opportunities — id, run_id, company, city, industry, total_score, rank, signal_count
  fact_leads     — id, run_id, opp_id, signal_id, pain_score, roi_score, confidence_score

IMPORTANT — dim_runs.id is a TEXT column (not numeric). Always get the latest run by:
  (SELECT id FROM dim_runs ORDER BY started_at DESC LIMIT 1)
  Do NOT use MAX(id) — it does string comparison and returns wrong results.

CRITICAL RULE — For ANY question about a specific company, query dim_signals DIRECTLY.
  Do NOT join with fact_leads or dim_opportunities for company lookups — those tables
  only cover a subset of signals (the ones linked to scored opportunities). Most job
  signals are in dim_signals but NOT in fact_leads. A JOIN will silently hide them.

Other rules:
  - For company name lookups ALWAYS use LIKE with % on BOTH sides for partial, case-insensitive matching:
      s.company_name LIKE '%Simon Fraser%'      ← correct (matches "Simon Fraser University", etc.)
      s.company_name = 'Simon Fraser University' ← wrong (exact match only; misses partial names)
    SQLite LIKE is case-insensitive for ASCII characters, so no separate ILIKE is needed.
  - Always qualify every column with its table alias when joining (avoids "ambiguous column").
  - The text of a signal is in the 'title' column of dim_signals (NOT 'signal_text').
  - Always scope to the session run unless the user asks about history.

EXAMPLE QUERIES (copy these patterns exactly):

-- All signals (jobs + news) for a specific company — DIRECT query, NO JOINs:
SELECT s.title, s.signal_type, s.source
FROM dim_signals s
WHERE s.company_name LIKE '%DoorDash%'
  AND s.run_id = (SELECT id FROM dim_runs ORDER BY started_at DESC LIMIT 1);

-- What roles is a company hiring for (job postings only):
SELECT s.title, s.source
FROM dim_signals s
WHERE s.signal_type = 'job'
  AND s.company_name LIKE '%DoorDash%'
  AND s.run_id = (SELECT id FROM dim_runs ORDER BY started_at DESC LIMIT 1);

-- Top hiring companies in the latest run:
SELECT s.company_name, COUNT(*) AS job_count
FROM dim_signals s
WHERE s.signal_type = 'job'
  AND s.company_name IS NOT NULL
  AND s.run_id = (SELECT id FROM dim_runs ORDER BY started_at DESC LIMIT 1)
GROUP BY s.company_name
ORDER BY job_count DESC
LIMIT 10;

-- All companies with job postings in the latest run:
SELECT DISTINCT s.company_name
FROM dim_signals s
WHERE s.signal_type = 'job'
  AND s.company_name IS NOT NULL
  AND s.run_id = (SELECT id FROM dim_runs ORDER BY started_at DESC LIMIT 1);

-- Join example (ONLY when scores/rankings are needed — always alias columns):
SELECT s.title, s.signal_type, o.total_score, o.rank
FROM dim_signals s
JOIN fact_leads f ON s.id = f.signal_id
JOIN dim_opportunities o ON f.opp_id = o.id
WHERE s.company_name LIKE '%Axiom%'
  AND s.run_id = (SELECT id FROM dim_runs ORDER BY started_at DESC LIMIT 1);
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
        _log.error("Groq call timed out after %.0fs:\n%s", _GROQ_TIMEOUT_SEC, traceback.format_exc())
        raise HTTPException(
            status_code=503,
            detail=_GROQ_UNAVAILABLE_MSG,
        ) from exc
    except HTTPException:
        raise
    except Exception as exc:
        _log.error("Groq call failed:\n%s", traceback.format_exc())
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


def _run_nl2sql_pipeline(
    question: str,
    db_path: str,
    api_key: str,
    run_id: str | int | None = None,
) -> tuple[str, str]:
    """
    Core NL2SQL pipeline. Isolated into its own function so tests can
    monkeypatch `marketscout.backend.nl2sql._run_nl2sql_pipeline` without
    needing the groq SDK installed.

    Args:
        question:  Natural-language question from the user.
        db_path:   Path to the Gold-layer SQLite database.
        api_key:   Groq API key.
        run_id:    The specific run the user is asking about (the current search
                   session run_id).  When provided it is injected into the SQL
                   prompt so Groq scopes every query to exactly this run instead
                   of guessing which run is "latest".

    Returns:
        (sql_query, insights) — both are non-empty strings.
    """
    schema_ctx = _sqlite_schema_context(db_path)

    # Build a run-scoping instruction: always prefer the explicit run_id when
    # available; fall back to started_at ordering when it is not.
    run_id_str = str(run_id).strip() if run_id is not None else ""
    if run_id_str:
        run_scope_hint = (
            f"CURRENT SESSION RUN ID: '{run_id_str}'\n"
            "When the user asks about companies, jobs, or signals from their "
            "current search, use this EXACT run_id in the WHERE clause:\n"
            f"  WHERE s.run_id = '{run_id_str}'\n"
            "Do NOT use MAX(id), MAX(run_id), or ORDER BY started_at — "
            "use the literal run_id above."
        )
    else:
        run_scope_hint = (
            "No session run_id provided. Use the latest run:\n"
            "  WHERE s.run_id = (SELECT id FROM dim_runs ORDER BY started_at DESC LIMIT 1)"
        )

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
        f"--- RUN SCOPE ---\n{run_scope_hint}\n\n"
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

    _log.debug("NL2SQL generated query: %s", sql_query)

    # Attempt SQL execution; on failure ask Groq to fix the query once.
    sql_error: str | None = None
    try:
        raw_results = _run_readonly_sql(db_path, sql_query)
    except Exception as first_exc:
        sql_error = str(first_exc)
        _log.warning(
            "SQL execution failed (will retry with error hint) — query=%r error=%s",
            sql_query, sql_error,
        )

    if sql_error:
        fix_prompt = (
            f"The following SQLite query failed with error: {sql_error}\n\n"
            f"Failing query:\n{sql_query}\n\n"
            "Common causes:\n"
            "- 'ambiguous column name': qualify every column with its table alias "
            "(e.g. s.run_id instead of run_id).\n"
            "- 'no such column': use 'title' for signal text, not 'signal_text'.\n"
            "- Wrong latest-run subquery: use "
            "(SELECT id FROM dim_runs ORDER BY started_at DESC LIMIT 1), "
            "NOT MAX(id) or MAX(run_id).\n\n"
            f"{_GOLD_SCHEMA_HINT.strip()}\n\n"
            f"Original question: {question.strip()}\n\n"
            "Return ONLY the corrected SQL query, no explanation."
        )
        try:
            sql_raw2 = _groq_generate(fix_prompt, api_key)
            sql_query2 = _extract_sql_from_model_output(sql_raw2)
            if sql_query2:
                _check_safety(sql_query2)
                _log.debug("NL2SQL retry query: %s", sql_query2)
                try:
                    raw_results = _run_readonly_sql(db_path, sql_query2)
                    sql_query = sql_query2  # report the working query
                    sql_error = None
                except Exception as retry_exc:
                    _log.error(
                        "SQL retry also failed — query=%r:\n%s",
                        sql_query2, traceback.format_exc(),
                    )
                    sql_error = str(retry_exc)
        except HTTPException:
            pass  # Groq unavailable on retry — fall through to original error

    if sql_error:
        raise HTTPException(
            status_code=500,
            detail=f"SQL execution failed: {sql_error}",
        )

    synthesis_prompt = (
        f"Original question: {question}\n\n"
        f"SQL query used: {sql_query}\n\n"
        f"Raw query results (JSON): {raw_results}\n\n"
        "Synthesize these data rows into a clear, one-paragraph business insight "
        "for a product manager. Focus on what the numbers mean, not how they were retrieved.\n\n"
        "If the results contain job postings (signal_type='job') for a company, "
        "summarize what they are actively hiring for and what that signals about their "
        "business priorities and growth areas.\n"
        "If a company has job postings but no news coverage, focus entirely on the "
        "hiring signals — describe the roles, the implied pain or growth pressure, "
        "and what product or service would be most relevant to pitch.\n"
        "If there are no results, say clearly that no signals were found for this "
        "company in the current run and suggest the user try a broader search."
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
