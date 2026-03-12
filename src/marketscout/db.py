"""SQLite persistence for MarketScout runs.

Schema:
  runs             — one row per run (city, industry, quality metrics)
  opportunities    — one row per opportunity per run, with workflow status
  signals          — one row per headline or job signal per run
  leads            — one row per company lead per run (when --write-leads is active)
  workflow_events  — audit log of opportunity status transitions

DB file location (in order of precedence):
  1. MARKETSCOUT_DB_PATH env var
  2. <cache_dir>/marketscout.db   (default: .cache/marketscout/marketscout.db)
"""

from __future__ import annotations

import os
import sqlite3
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ── Constants ─────────────────────────────────────────────────────────────────

VALID_STATUSES: tuple[str, ...] = (
    "discovered",
    "under_review",
    "prioritized",
    "rejected",
    "pursued",
)


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
    """Create all tables if they do not already exist; migrate existing tables."""
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
            id                   INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id               TEXT,
            title                TEXT,
            problem              TEXT,
            ai_category          TEXT,
            pain_score           REAL,
            automation_potential REAL,
            roi_signal           REAL,
            confidence           REAL,
            status               TEXT DEFAULT 'discovered',
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

        CREATE TABLE IF NOT EXISTS workflow_events (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            opp_id      INTEGER,
            from_status TEXT,
            to_status   TEXT,
            note        TEXT,
            changed_at  TEXT,
            FOREIGN KEY(opp_id) REFERENCES opportunities(id)
        );
    """)
    conn.commit()

    # Migrate: add status column to opportunities if it came from an older schema.
    try:
        conn.execute("ALTER TABLE opportunities ADD COLUMN status TEXT DEFAULT 'discovered'")
        conn.commit()
    except sqlite3.OperationalError:
        pass  # column already exists


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
                 pain_score, automation_potential, roi_signal, confidence, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'discovered')
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


# ── Workflow ───────────────────────────────────────────────────────────────────

def update_opportunity_status(
    conn: sqlite3.Connection,
    opp_id: int,
    new_status: str,
    note: str | None = None,
) -> bool:
    """
    Transition opportunity to new_status and record the event in workflow_events.
    Returns True if the opportunity was found, False if opp_id does not exist.
    Raises ValueError for unrecognised status values.
    """
    if new_status not in VALID_STATUSES:
        raise ValueError(f"Invalid status '{new_status}'. Valid: {', '.join(VALID_STATUSES)}")
    cur = conn.execute("SELECT status FROM opportunities WHERE id = ?", (opp_id,))
    row = cur.fetchone()
    if row is None:
        return False
    from_status = row["status"] or "discovered"
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn.execute("UPDATE opportunities SET status = ? WHERE id = ?", (new_status, opp_id))
    conn.execute(
        "INSERT INTO workflow_events (opp_id, from_status, to_status, note, changed_at) VALUES (?, ?, ?, ?, ?)",
        (opp_id, from_status, new_status, note, now),
    )
    conn.commit()
    return True


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


def list_opportunities(
    conn: sqlite3.Connection,
    city: str | None = None,
    industry: str | None = None,
    status: str | None = None,
    limit: int = 20,
) -> list[sqlite3.Row]:
    """
    Return opportunities with their run context and workflow status.
    Optionally filter by city, industry, and/or status.
    """
    conditions: list[str] = []
    params: list[Any] = []
    if city:
        conditions.append("lower(r.city) = lower(?)")
        params.append(city)
    if industry:
        conditions.append("lower(r.industry) = lower(?)")
        params.append(industry)
    if status:
        conditions.append("o.status = ?")
        params.append(status)
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    params.append(limit)
    cur = conn.execute(
        f"""
        SELECT o.id, o.title, o.pain_score, o.roi_signal, o.confidence,
               o.ai_category, o.status,
               r.city, r.industry, r.created_at, r.run_id
        FROM opportunities o
        JOIN runs r ON o.run_id = r.run_id
        {where}
        ORDER BY r.created_at DESC, o.pain_score DESC
        LIMIT ?
        """,
        params,
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


def get_trend_data(
    conn: sqlite3.Connection,
    city: str,
    industry: str,
    limit_runs: int = 5,
) -> list[dict[str, Any]]:
    """
    Return trend data for opportunities across the last N runs for city + industry.

    Each entry:
        title        — opportunity title
        appearances  — how many of the last N runs it appeared in
        avg_pain     — average pain_score across those appearances
        trend        — "rising" | "stable" | "falling" | "single"
                       Derived by comparing the older-half vs newer-half average pain.

    Sorted by appearances DESC, avg_pain DESC.
    """
    cur = conn.execute(
        """
        SELECT run_id FROM runs
        WHERE lower(city) = lower(?) AND lower(industry) = lower(?)
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (city, industry, limit_runs),
    )
    run_ids = [r["run_id"] for r in cur.fetchall()]
    if not run_ids:
        return []

    placeholders = ",".join("?" * len(run_ids))
    cur2 = conn.execute(
        f"""
        SELECT o.title, o.pain_score, r.created_at
        FROM opportunities o
        JOIN runs r ON o.run_id = r.run_id
        WHERE o.run_id IN ({placeholders})
        ORDER BY r.created_at ASC
        """,
        run_ids,
    )
    rows = cur2.fetchall()

    # Group pain scores per title in chronological order
    title_pains: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        title_pains[r["title"]].append(r["pain_score"])

    result: list[dict[str, Any]] = []
    for title, pains in title_pains.items():
        appearances = len(pains)
        avg_pain = sum(pains) / appearances
        if appearances <= 1:
            trend = "single"
        else:
            mid = appearances // 2
            older_avg = sum(pains[:mid]) / mid
            newer_avg = sum(pains[mid:]) / (appearances - mid)
            diff = newer_avg - older_avg
            if diff > 0.5:
                trend = "rising"
            elif diff < -0.5:
                trend = "falling"
            else:
                trend = "stable"
        result.append({
            "title": title,
            "appearances": appearances,
            "avg_pain": round(avg_pain, 2),
            "trend": trend,
        })

    result.sort(key=lambda x: (-x["appearances"], -x["avg_pain"]))
    return result
