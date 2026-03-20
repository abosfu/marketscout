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

import json
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

    # Migrate: add columns that may be absent from older schemas.
    _migrations = [
        ("opportunities", "status",               "TEXT DEFAULT 'discovered'"),
        ("opportunities", "support_level",         "TEXT DEFAULT 'moderate'"),
        ("opportunities", "is_padded",             "INTEGER DEFAULT 0"),
        ("opportunities", "signal_age_days_avg",   "REAL"),
        ("opportunities", "unique_sources_count",  "INTEGER DEFAULT 0"),
        ("opportunities", "trend_key",             "TEXT DEFAULT ''"),
        ("opportunities", "recommendation",        "TEXT DEFAULT 'monitor'"),
        ("opportunities", "suggested_actions",     "TEXT DEFAULT '[]'"),
        ("opportunities", "leads",                 "TEXT DEFAULT '[]'"),
    ]
    for table, column, typedef in _migrations:
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {typedef}")
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
                 pain_score, automation_potential, roi_signal, confidence, status,
                 support_level, is_padded, signal_age_days_avg, unique_sources_count,
                 trend_key, recommendation, suggested_actions, leads)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'discovered', ?, ?, ?, ?, ?, ?, ?, ?)
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
                getattr(opp, "support_level", "moderate"),
                1 if getattr(opp, "is_padded", False) else 0,
                getattr(opp, "signal_age_days_avg", None),
                getattr(opp, "unique_sources_count", 0),
                getattr(opp, "trend_key", ""),
                getattr(opp, "recommendation", "monitor"),
                json.dumps(getattr(opp, "suggested_actions", []) or []),
                json.dumps([
                    ld.model_dump() if hasattr(ld, "model_dump") else dict(ld)
                    for ld in (getattr(opp, "leads", []) or [])
                ]),
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
            MAX(COALESCE(NULLIF(trend_key, ''), NULL)) AS trend_key,
            AVG(pain_score)                                             AS avg_pain,
            AVG(roi_signal)                                             AS avg_roi,
            AVG(confidence)                                             AS avg_confidence,
            COUNT(*)                                                    AS appearances,
            SUM(CASE WHEN is_padded = 1 THEN 1 ELSE 0 END)            AS padded_count,
            SUM(CASE WHEN support_level = 'strong' THEN 1 ELSE 0 END) AS strong_count,
            SUM(CASE WHEN support_level = 'weak'   THEN 1 ELSE 0 END) AS weak_count
        FROM opportunities
        WHERE run_id IN ({placeholders})
        GROUP BY title
        ORDER BY appearances DESC, avg_pain DESC
        """,
        run_ids,
    )
    return run_rows, cur2.fetchall()


def _classify_trend_quality(
    appearances: int,
    trend: str,
    avg_confidence: float,
    padded_count: int,
    strong_count: int,
) -> str:
    """
    Classify the actionability of a recurring opportunity based on quality dimensions.

    Returns one of:
      "investable"  — repeated strong support, rising or stable, confidence >= 0.5
      "monitor"     — moderate or mixed support; worth watching but not yet actionable
      "noise"       — majority of appearances are padded or weak; disregard
      "emerging"    — appeared once this window with strong support; watch closely
      "declining"   — clear downward pain trend regardless of support level

    Rules (evaluated in order):
      1. noise     if padded_count >= ceil(appearances / 2)
      2. declining if trend == "falling"
      3. emerging  if appearances == 1 and strong_count >= 1
      4. monitor   if appearances == 1 (single, not strong)
      5. investable if strong_count >= half of appearances AND avg_confidence >= 0.5
                     AND trend in (rising, stable)
      6. monitor   otherwise
    """
    # 1. Noise: more than half of appearances are padded
    if appearances > 0 and padded_count * 2 >= appearances:
        return "noise"
    # 2. Declining trend
    if trend == "falling":
        return "declining"
    # 3. Emerging: appeared once this window with strong support
    if appearances == 1 and strong_count >= 1:
        return "emerging"
    # 4. Single appearance, not strongly supported
    if appearances == 1:
        return "monitor"
    # 5. Multi-appearance: investable when strong majority + decent confidence
    if strong_count * 2 >= appearances and avg_confidence >= 0.5 and trend in ("rising", "stable"):
        return "investable"
    # 6. Moderate / mixed
    return "monitor"


def _build_history_summary(
    appearances: int,
    limit_runs: int,
    trend_quality: str,
    padded_count: int,
    strong_count: int,
) -> str:
    """
    Return a concise plain-language description of historical persistence.
    Grounded in actual stored run data — not boilerplate.
    """
    if trend_quality == "investable":
        return (
            f"appeared in {appearances}/{limit_runs} runs with strong support "
            f"({strong_count} strong appearance(s))"
        )
    if trend_quality == "noise":
        return (
            f"appeared {appearances}x but {padded_count} appearance(s) were padded "
            "— treat as template noise"
        )
    if trend_quality == "emerging":
        return "new strong signal this cycle — not yet repeated; monitor closely"
    if trend_quality == "declining":
        return f"appeared {appearances}x but pain score is falling — deprioritise"
    if appearances > 1:
        return (
            f"appeared {appearances}/{limit_runs} runs with mixed or moderate support "
            f"({strong_count} strong appearance(s))"
        )
    return "single appearance this window — insufficient history"


def get_trend_data(
    conn: sqlite3.Connection,
    city: str,
    industry: str,
    limit_runs: int = 5,
) -> list[dict[str, Any]]:
    """
    Return quality-aware trend data for opportunities across the last N runs.

    Each entry:
        title           — opportunity title
        appearances     — how many of the last N runs it appeared in
        avg_pain        — average pain_score across those appearances
        avg_confidence  — average confidence across those appearances
        trend           — "rising" | "stable" | "falling" | "single"
                          Derived by comparing older-half vs newer-half average pain.
        trend_quality   — "investable" | "monitor" | "noise" | "emerging" | "declining"
                          Quality-aware classification (considers support_level, is_padded).
        padded_count    — number of appearances where is_padded was True
        strong_count    — number of appearances where support_level was 'strong'
        weak_count      — number of appearances where support_level was 'weak'
        history_summary — plain-language description of historical persistence

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
        SELECT o.title, o.pain_score, o.confidence,
               o.support_level, o.is_padded, r.created_at
        FROM opportunities o
        JOIN runs r ON o.run_id = r.run_id
        WHERE o.run_id IN ({placeholders})
        ORDER BY r.created_at ASC
        """,
        run_ids,
    )
    rows = cur2.fetchall()

    # Accumulate per-title data in chronological order
    title_data: dict[str, dict[str, Any]] = {}
    for r in rows:
        title = r["title"]
        if title not in title_data:
            title_data[title] = {
                "pains": [],
                "confidences": [],
                "padded_count": 0,
                "strong_count": 0,
                "weak_count": 0,
            }
        title_data[title]["pains"].append(r["pain_score"] or 0.0)
        title_data[title]["confidences"].append(r["confidence"] or 0.0)
        if r["is_padded"]:
            title_data[title]["padded_count"] += 1
        support = (r["support_level"] or "moderate").lower()
        if support == "strong":
            title_data[title]["strong_count"] += 1
        elif support == "weak":
            title_data[title]["weak_count"] += 1

    result: list[dict[str, Any]] = []
    for title, data in title_data.items():
        pains = data["pains"]
        confidences = data["confidences"]
        appearances = len(pains)
        avg_pain = sum(pains) / appearances
        avg_confidence = sum(confidences) / appearances
        padded_count = data["padded_count"]
        strong_count = data["strong_count"]
        weak_count = data["weak_count"]

        # Pain direction: compare older half vs newer half
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

        trend_quality = _classify_trend_quality(
            appearances=appearances,
            trend=trend,
            avg_confidence=avg_confidence,
            padded_count=padded_count,
            strong_count=strong_count,
        )
        history_summary = _build_history_summary(
            appearances=appearances,
            limit_runs=limit_runs,
            trend_quality=trend_quality,
            padded_count=padded_count,
            strong_count=strong_count,
        )

        result.append({
            "title": title,
            "appearances": appearances,
            "avg_pain": round(avg_pain, 2),
            "avg_confidence": round(avg_confidence, 3),
            "trend": trend,
            "trend_quality": trend_quality,
            "padded_count": padded_count,
            "strong_count": strong_count,
            "weak_count": weak_count,
            "history_summary": history_summary,
        })

    result.sort(key=lambda x: (-x["appearances"], -x["avg_pain"]))
    return result
