"""SQLite persistence for MarketScout runs.

Schema:
  runs         — one row per run (city, industry, quality metrics)
  opportunities — one row per opportunity per run
  signals       — one row per headline or job signal per run
  leads         — one row per company lead per run (when --write-leads is active)

DB file location (in order of precedence):
  1. MARKETSCOUT_DB_PATH env var
  2. <cache_dir>/marketscout.db   (default: .cache/marketscout/marketscout.db)
"""

from __future__ import annotations

import os
import sqlite3
import uuid
from pathlib import Path
from typing import Any


# ── Path resolution ───────────────────────────────────────────────────────────

def get_db_path() -> Path:
    """Return the SQLite DB file path. Override with MARKETSCOUT_DB_PATH."""
    val = os.environ.get("MARKETSCOUT_DB_PATH")
    if val and val.strip():
        return Path(val.strip())
    from marketscout.config import get_cache_dir
    return get_cache_dir() / "marketscout.db"


# ── Connection ────────────────────────────────────────────────────────────────

def get_connection(db_path: Path | None = None) -> sqlite3.Connection:
    """
    Open the SQLite connection, creating the file and schema if needed.
    Returns a connection with row_factory = sqlite3.Row set.
    """
    if db_path is None:
        db_path = get_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    return conn


# ── Schema ────────────────────────────────────────────────────────────────────

def init_db(conn: sqlite3.Connection) -> None:
    """Create all tables if they do not already exist."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS runs (
            run_id                TEXT PRIMARY KEY,
            created_at            TEXT,
            city                  TEXT,
            industry              TEXT,
            strategy_mode         TEXT,
            deterministic         INTEGER,
            coverage_score        REAL,
            freshness_window_days INTEGER,
            source_mix_score      REAL,
            headlines_count       INTEGER,
            jobs_count            INTEGER
        );

        CREATE TABLE IF NOT EXISTS opportunities (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id              TEXT,
            title               TEXT,
            problem             TEXT,
            ai_category         TEXT,
            pain_score          REAL,
            automation_potential REAL,
            roi_signal          REAL,
            confidence          REAL,
            FOREIGN KEY(run_id) REFERENCES runs(run_id)
        );

        CREATE TABLE IF NOT EXISTS signals (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id       TEXT,
            source_type  TEXT,
            provider     TEXT,
            title        TEXT,
            link         TEXT,
            published_at TEXT,
            company      TEXT,
            FOREIGN KEY(run_id) REFERENCES runs(run_id)
        );

        CREATE TABLE IF NOT EXISTS leads (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id          TEXT,
            company         TEXT,
            job_count       INTEGER,
            readiness_score REAL,
            top_keywords    TEXT,
            example_links   TEXT,
            FOREIGN KEY(run_id) REFERENCES runs(run_id)
        );
    """)
    conn.commit()


# ── Write ─────────────────────────────────────────────────────────────────────

def generate_run_id() -> str:
    """Return a new random run ID (UUID4)."""
    return str(uuid.uuid4())


def save_run(
    conn: sqlite3.Connection,
    run_id: str,
    city: str,
    industry: str,
    strategy: Any,             # StrategyOutput (Pydantic model)
    headlines: list[dict],
    jobs: list[dict],
    fetch_status: dict,
    run_metadata: dict,
    strategy_mode: str,
    leads: list[dict] | None = None,
) -> None:
    """
    Persist a complete run to the database in a single transaction.

    Args:
        strategy:      StrategyOutput Pydantic instance.
        leads:         List of dicts (from dataclasses.asdict(LeadRow)).
                       Pass None or omit to skip lead persistence.
    """
    dq = strategy.data_quality
    su = strategy.signals_used

    conn.execute(
        """
        INSERT INTO runs
            (run_id, created_at, city, industry, strategy_mode, deterministic,
             coverage_score, freshness_window_days, source_mix_score,
             headlines_count, jobs_count)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            run_metadata.get("started_at_iso", ""),
            city,
            industry,
            strategy_mode,
            1 if run_metadata.get("deterministic") else 0,
            dq.coverage_score,
            dq.freshness_window_days,
            dq.source_mix_score,
            su.headlines_count,
            su.jobs_count,
        ),
    )

    for opp in strategy.opportunity_map:
        conn.execute(
            """
            INSERT INTO opportunities
                (run_id, title, problem, ai_category,
                 pain_score, automation_potential, roi_signal, confidence)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                opp.title,
                opp.problem,
                opp.ai_category,
                opp.pain_score,
                opp.automation_potential,
                opp.roi_signal,
                opp.confidence,
            ),
        )

    h_provider = (fetch_status.get("headlines") or {}).get("provider", "")
    j_provider = (fetch_status.get("jobs") or {}).get("provider", "")

    for h in headlines:
        conn.execute(
            """
            INSERT INTO signals
                (run_id, source_type, provider, title, link, published_at, company)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id, "headline", h_provider,
                (h.get("title") or "").strip(),
                (h.get("link") or "").strip(),
                (h.get("published") or "").strip(),
                None,
            ),
        )

    for j in jobs:
        conn.execute(
            """
            INSERT INTO signals
                (run_id, source_type, provider, title, link, published_at, company)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id, "job", j_provider,
                (j.get("title") or "").strip(),
                (j.get("link") or "").strip(),
                (j.get("published") or "").strip(),
                (j.get("company") or "").strip() or None,
            ),
        )

    if leads:
        for lead in leads:
            conn.execute(
                """
                INSERT INTO leads
                    (run_id, company, job_count, readiness_score, top_keywords, example_links)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    lead.get("company", ""),
                    lead.get("job_count", 0),
                    lead.get("readiness_score", 0),
                    lead.get("top_keywords", ""),
                    lead.get("example_links", ""),
                ),
            )

    conn.commit()


# ── Read ──────────────────────────────────────────────────────────────────────

def list_runs(conn: sqlite3.Connection, limit: int = 10) -> list[sqlite3.Row]:
    """Return up to `limit` runs ordered by created_at descending."""
    cur = conn.execute(
        """
        SELECT run_id, created_at, city, industry, strategy_mode,
               headlines_count, jobs_count, coverage_score
        FROM runs
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (limit,),
    )
    return cur.fetchall()


def compare_runs(
    conn: sqlite3.Connection,
    city: str,
    industry: str,
    limit_runs: int = 3,
) -> tuple[list[sqlite3.Row], list[sqlite3.Row]]:
    """
    Return (recent_runs, aggregated_opportunities) for the latest N runs
    matching city + industry (case-insensitive).

    Aggregated opportunities are grouped by title and show average scores
    plus the number of runs in which they appeared.
    """
    cur = conn.execute(
        """
        SELECT run_id, created_at, strategy_mode, headlines_count, jobs_count
        FROM runs
        WHERE lower(city) = lower(?) AND lower(industry) = lower(?)
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (city, industry, limit_runs),
    )
    run_rows = cur.fetchall()
    if not run_rows:
        return [], []

    run_ids = [r["run_id"] for r in run_rows]
    placeholders = ",".join("?" * len(run_ids))

    cur2 = conn.execute(
        f"""
        SELECT
            title,
            AVG(pain_score)          AS avg_pain,
            AVG(roi_signal)          AS avg_roi,
            AVG(confidence)          AS avg_confidence,
            COUNT(*)                 AS appearances
        FROM opportunities
        WHERE run_id IN ({placeholders})
        GROUP BY title
        ORDER BY appearances DESC, avg_pain DESC
        """,
        run_ids,
    )
    return run_rows, cur2.fetchall()
