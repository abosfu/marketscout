"""BI export layer: generate Power BI / Tableau-ready CSVs from a single MarketScout run.

Reads directly from the SQLite database and produces three CSV files in a star-schema layout:

  dim_opportunities.csv  — one row per opportunity (grain: run_id + trend_key)
  fact_leads.csv         — one row per lead per opportunity (1:N from dim_opportunities)
  fact_actions.csv       — one row per action per opportunity (1:N from dim_opportunities)

Join key for BI: (run_id, trend_key)

Usage:
    from marketscout.bi_export import export_to_bi
    paths = export_to_bi(db_path="/path/to/marketscout.db",
                         export_dir="out/run/bi_exports",
                         run_id="<uuid>")

Returns a dict {"dim_opportunities": Path, "fact_leads": Path, "fact_actions": Path}.
Raises FileNotFoundError if db_path does not exist.
Raises sqlite3.OperationalError if the run_id query fails (e.g. missing table).
"""

from __future__ import annotations

import csv
import json
import sqlite3
from pathlib import Path

# ── Column definitions (single source of truth for headers) ───────────────────

DIM_OPPORTUNITIES_FIELDS = [
    "run_id",
    "trend_key",
    "title",
    "problem",
    "ai_category",
    "opportunity_type",
    "pain_score",
    "urgency_score",   # derived: round(confidence × pain_score, 2)
    "roi_signal",
    "confidence",
    "recommendation",
]

FACT_LEADS_FIELDS = [
    "run_id",
    "trend_key",
    "company_name",
    "reason",
    "signal_type",
    "priority_score",
]

FACT_ACTIONS_FIELDS = [
    "run_id",
    "trend_key",
    "action_index",   # 0-based position within the opportunity's action list
    "action_text",
]

# ── Derived-field helpers ──────────────────────────────────────────────────────

# Same mapping as strategy._OPPORTUNITY_TYPE_MAP — kept local to avoid coupling.
_AI_CATEGORY_TO_TYPE: dict[str, str] = {
    "Operational efficiency": "operational",
    "Cost reduction":         "operational",
    "Risk mitigation":        "compliance",
    "Regulatory & permits":   "compliance",
    "Market entry":           "strategic",
    "Growth and scale":       "strategic",
    "Partnership and M&A":    "strategic",
}


def _opportunity_type(ai_category: str) -> str:
    return _AI_CATEGORY_TO_TYPE.get(ai_category or "", "operational")


def _urgency_score(confidence: float, pain_score: float) -> float:
    """Composite urgency proxy: confidence × pain_score, rounded to 2 dp."""
    return round((confidence or 0.0) * (pain_score or 0.0), 2)


def _parse_json_list(raw: str | None, field_name: str = "") -> list:
    """Safely parse a JSON list from a DB TEXT column; returns [] on any failure."""
    if not raw:
        return []
    try:
        result = json.loads(raw)
        return result if isinstance(result, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


# ── Main export function ───────────────────────────────────────────────────────

def export_to_bi(db_path: str, export_dir: str, run_id: str) -> dict[str, Path]:
    """
    Export a single run from SQLite to three BI-ready CSV files.

    Args:
        db_path:    Absolute path to the MarketScout SQLite database file.
        export_dir: Directory where the CSVs will be written (created if absent).
        run_id:     The run UUID to export (must exist in the 'opportunities' table).

    Returns:
        Dict mapping table name to output Path:
            {"dim_opportunities": Path, "fact_leads": Path, "fact_actions": Path}

    Raises:
        FileNotFoundError: if db_path does not exist.
        sqlite3.OperationalError: if the opportunities table or columns are missing.
    """
    db_file = Path(db_path)
    if not db_file.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")

    export_path = Path(export_dir)
    export_path.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_file))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT
                run_id,
                COALESCE(trend_key, '')        AS trend_key,
                COALESCE(title, '')            AS title,
                COALESCE(problem, '')          AS problem,
                COALESCE(ai_category, '')      AS ai_category,
                COALESCE(pain_score, 0.0)      AS pain_score,
                COALESCE(roi_signal, 0.0)      AS roi_signal,
                COALESCE(confidence, 0.0)      AS confidence,
                COALESCE(recommendation, '')   AS recommendation,
                COALESCE(suggested_actions, '[]') AS suggested_actions,
                COALESCE(leads, '[]')          AS leads
            FROM opportunities
            WHERE run_id = ?
            ORDER BY pain_score DESC, confidence DESC
            """,
            (run_id,),
        ).fetchall()
    finally:
        conn.close()

    dim_path = export_path / "dim_opportunities.csv"
    fact_leads_path = export_path / "fact_leads.csv"
    fact_actions_path = export_path / "fact_actions.csv"

    # ── dim_opportunities.csv ─────────────────────────────────────────────────
    with dim_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=DIM_OPPORTUNITIES_FIELDS, extrasaction="raise")
        writer.writeheader()
        for row in rows:
            pain = float(row["pain_score"])
            conf = float(row["confidence"])
            ai_cat = str(row["ai_category"])
            writer.writerow({
                "run_id":           str(row["run_id"]),
                "trend_key":        str(row["trend_key"]),
                "title":            str(row["title"]),
                "problem":          str(row["problem"]),
                "ai_category":      ai_cat,
                "opportunity_type": _opportunity_type(ai_cat),
                "pain_score":       pain,
                "urgency_score":    _urgency_score(conf, pain),
                "roi_signal":       float(row["roi_signal"]),
                "confidence":       conf,
                "recommendation":   str(row["recommendation"]),
            })

    # ── fact_leads.csv ────────────────────────────────────────────────────────
    with fact_leads_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FACT_LEADS_FIELDS, extrasaction="raise")
        writer.writeheader()
        for row in rows:
            trend_key = str(row["trend_key"])
            leads = _parse_json_list(row["leads"], "leads")
            for lead in leads:
                if not isinstance(lead, dict):
                    continue
                writer.writerow({
                    "run_id":       str(row["run_id"]),
                    "trend_key":    trend_key,
                    "company_name": str(lead.get("company_name", "")),
                    "reason":       str(lead.get("reason", "")),
                    "signal_type":  str(lead.get("signal_type", "")),
                    "priority_score": float(lead.get("priority_score", 0.0)),
                })

    # ── fact_actions.csv ──────────────────────────────────────────────────────
    with fact_actions_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FACT_ACTIONS_FIELDS, extrasaction="raise")
        writer.writeheader()
        for row in rows:
            trend_key = str(row["trend_key"])
            actions = _parse_json_list(row["suggested_actions"], "suggested_actions")
            for idx, action in enumerate(actions):
                if not isinstance(action, str):
                    continue
                writer.writerow({
                    "run_id":       str(row["run_id"]),
                    "trend_key":    trend_key,
                    "action_index": idx,
                    "action_text":  action,
                })

    return {
        "dim_opportunities": dim_path,
        "fact_leads":        fact_leads_path,
        "fact_actions":      fact_actions_path,
    }
