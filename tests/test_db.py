"""Tests for src/marketscout/db.py and CLI history/compare commands."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from marketscout.db import (
    VALID_STATUSES,
    _classify_trend_quality,
    compare_runs,
    generate_run_id,
    get_connection,
    get_db_path,
    get_trend_data,
    init_db,
    list_opportunities,
    list_runs,
    save_run,
    update_opportunity_status,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _tmp_conn(tmp_path: Path):
    """Return an in-memory-style connection using a temp file."""
    db_path = tmp_path / "test.db"
    return get_connection(db_path)


def _make_strategy(
    pain: float = 7.0,
    city: str = "Vancouver",
    industry: str = "Construction",
    support_level: str = "moderate",
    is_padded: bool = False,
    signal_age_days_avg: float | None = None,
    unique_sources_count: int = 2,
    confidence: float = 0.8,
):
    """Build a minimal StrategyOutput-compatible mock with all signal quality fields."""
    opp = SimpleNamespace(
        title="Test Opp",
        problem="Test problem",
        ai_category="Automation",
        pain_score=pain,
        automation_potential=6.0,
        roi_signal=5.0,
        confidence=confidence,
        support_level=support_level,
        is_padded=is_padded,
        signal_age_days_avg=signal_age_days_avg,
        unique_sources_count=unique_sources_count,
        trend_key="operational_efficiency::test_problem",
        recommendation="monitor",
    )
    dq = SimpleNamespace(coverage_score=0.75, freshness_window_days=7, source_mix_score=0.6)
    su = SimpleNamespace(headlines_count=2, jobs_count=3)
    return SimpleNamespace(
        city=city,
        industry=industry,
        data_quality=dq,
        signals_used=su,
        opportunity_map=[opp],
    )


def _save_one(conn, run_id: str = "abc-123", city: str = "Vancouver", industry: str = "Construction"):
    strategy = _make_strategy(city=city, industry=industry)
    headlines = [{"title": "H1", "link": "https://example.com/h1", "published": "2024-01-01"}]
    jobs = [{"title": "J1", "link": "https://example.com/j1", "published": "2024-01-01", "company": "Acme"}]
    fetch_status = {
        "headlines": {"provider": "google_news_rss", "status": "live"},
        "jobs": {"provider": "adzuna", "status": "live"},
    }
    run_metadata = {"started_at_iso": "2024-01-01T00:00:00Z", "deterministic": True}
    save_run(
        conn=conn,
        run_id=run_id,
        city=city,
        industry=industry,
        strategy=strategy,
        headlines=headlines,
        jobs=jobs,
        fetch_status=fetch_status,
        run_metadata=run_metadata,
        strategy_mode="mock",
    )


# ── init_db ───────────────────────────────────────────────────────────────────

def test_init_db_creates_tables(tmp_path):
    conn = _tmp_conn(tmp_path)
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert {"runs", "opportunities", "signals", "leads"} <= tables
    conn.close()


def test_init_db_idempotent(tmp_path):
    """Calling init_db twice must not raise."""
    conn = _tmp_conn(tmp_path)
    init_db(conn)  # second call
    conn.close()


# ── generate_run_id ────────────────────────────────────────────────────────────

def test_generate_run_id_unique():
    ids = {generate_run_id() for _ in range(100)}
    assert len(ids) == 100


def test_generate_run_id_format():
    rid = generate_run_id()
    # UUID4 has format xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx
    assert len(rid) == 36
    assert rid[14] == "4"


# ── save_run / list_runs ───────────────────────────────────────────────────────

def test_save_run_inserts_run_row(tmp_path):
    conn = _tmp_conn(tmp_path)
    _save_one(conn, run_id="run-1")
    rows = list_runs(conn)
    assert len(rows) == 1
    assert rows[0]["run_id"] == "run-1"
    conn.close()


def test_save_run_inserts_opportunity_row(tmp_path):
    conn = _tmp_conn(tmp_path)
    _save_one(conn, run_id="run-2")
    opps = conn.execute("SELECT * FROM opportunities WHERE run_id='run-2'").fetchall()
    assert len(opps) == 1
    assert opps[0]["title"] == "Test Opp"
    conn.close()


def test_save_run_inserts_signal_rows(tmp_path):
    conn = _tmp_conn(tmp_path)
    _save_one(conn, run_id="run-3")
    sigs = conn.execute("SELECT source_type FROM signals WHERE run_id='run-3'").fetchall()
    types = [s["source_type"] for s in sigs]
    assert "headline" in types
    assert "job" in types
    conn.close()


def test_save_run_inserts_lead_rows(tmp_path):
    conn = _tmp_conn(tmp_path)
    strategy = _make_strategy()
    leads = [{"company": "Acme", "job_count": 3, "readiness_score": 7.5, "top_keywords": "python", "example_links": "http://x.com"}]
    save_run(
        conn=conn,
        run_id="run-4",
        city="Vancouver",
        industry="Construction",
        strategy=strategy,
        headlines=[],
        jobs=[],
        fetch_status={},
        run_metadata={"started_at_iso": "2024-01-01T00:00:00Z", "deterministic": False},
        strategy_mode="mock",
        leads=leads,
    )
    lead_rows = conn.execute("SELECT * FROM leads WHERE run_id='run-4'").fetchall()
    assert len(lead_rows) == 1
    assert lead_rows[0]["company"] == "Acme"
    conn.close()


def test_save_run_none_leads_skips_insert(tmp_path):
    conn = _tmp_conn(tmp_path)
    strategy = _make_strategy()
    save_run(
        conn=conn,
        run_id="run-5",
        city="Vancouver",
        industry="Construction",
        strategy=strategy,
        headlines=[],
        jobs=[],
        fetch_status={},
        run_metadata={"started_at_iso": "2024-01-01T00:00:00Z", "deterministic": False},
        strategy_mode="mock",
        leads=None,
    )
    lead_rows = conn.execute("SELECT * FROM leads WHERE run_id='run-5'").fetchall()
    assert len(lead_rows) == 0
    conn.close()


def test_list_runs_returns_newest_first(tmp_path):
    conn = _tmp_conn(tmp_path)
    # Insert two runs with different timestamps
    strategy = _make_strategy()
    for run_id, ts in [("run-a", "2024-01-01T00:00:00Z"), ("run-b", "2024-06-01T00:00:00Z")]:
        save_run(
            conn=conn, run_id=run_id, city="Vancouver", industry="Construction",
            strategy=strategy, headlines=[], jobs=[], fetch_status={},
            run_metadata={"started_at_iso": ts, "deterministic": False},
            strategy_mode="mock",
        )
    rows = list_runs(conn, limit=10)
    assert rows[0]["run_id"] == "run-b"
    assert rows[1]["run_id"] == "run-a"
    conn.close()


def test_list_runs_respects_limit(tmp_path):
    conn = _tmp_conn(tmp_path)
    for i in range(5):
        _save_one(conn, run_id=f"run-{i:02d}")
    rows = list_runs(conn, limit=3)
    assert len(rows) == 3
    conn.close()


# ── compare_runs ───────────────────────────────────────────────────────────────

def test_compare_runs_returns_empty_for_no_data(tmp_path):
    conn = _tmp_conn(tmp_path)
    run_rows, opp_rows = compare_runs(conn, "Vancouver", "Construction")
    assert run_rows == []
    assert opp_rows == []
    conn.close()


def test_compare_runs_aggregates_opportunities(tmp_path):
    conn = _tmp_conn(tmp_path)
    for i in range(2):
        _save_one(conn, run_id=f"comp-{i}", city="Vancouver", industry="Construction")
    run_rows, opp_rows = compare_runs(conn, "Vancouver", "Construction", limit_runs=3)
    assert len(run_rows) == 2
    assert len(opp_rows) >= 1
    assert opp_rows[0]["title"] == "Test Opp"
    assert opp_rows[0]["appearances"] == 2
    conn.close()


def test_compare_runs_case_insensitive(tmp_path):
    conn = _tmp_conn(tmp_path)
    _save_one(conn, run_id="ci-1", city="Vancouver", industry="Construction")
    run_rows, _ = compare_runs(conn, "VANCOUVER", "construction")
    assert len(run_rows) == 1
    conn.close()


# ── cmd_history CLI ────────────────────────────────────────────────────────────

def _src_env(tmp_path: Path, **extra) -> dict:
    """Build subprocess env with src/ on PYTHONPATH so marketscout is importable."""
    import os
    src = str(Path(__file__).parent.parent / "src")
    env = dict(os.environ)
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{src}:{existing}" if existing else src
    env.update(extra)
    return env


def test_cmd_history_no_db(tmp_path):
    """history command handles a fresh empty DB gracefully."""
    db_path = tmp_path / "empty.db"
    result = subprocess.run(
        [sys.executable, "-m", "marketscout", "history", "--limit", "5"],
        capture_output=True, text=True,
        env=_src_env(tmp_path, MARKETSCOUT_DB_PATH=str(db_path)),
    )
    assert result.returncode == 0, result.stderr
    assert "No runs found" in result.stdout


def test_cmd_compare_no_data(tmp_path):
    """compare command handles missing city/industry data gracefully."""
    db_path = tmp_path / "empty.db"
    result = subprocess.run(
        [sys.executable, "-m", "marketscout", "compare", "--city", "Vancouver", "--industry", "Construction"],
        capture_output=True, text=True,
        env=_src_env(tmp_path, MARKETSCOUT_DB_PATH=str(db_path)),
    )
    assert result.returncode == 0, result.stderr
    assert "No runs found" in result.stdout


# ── workflow: update_opportunity_status ───────────────────────────────────────

def test_valid_statuses_tuple():
    assert "discovered" in VALID_STATUSES
    assert "prioritized" in VALID_STATUSES
    assert "rejected" in VALID_STATUSES
    assert "pursued" in VALID_STATUSES


def test_update_status_transitions(tmp_path):
    conn = _tmp_conn(tmp_path)
    _save_one(conn, run_id="ws-1")
    opp_id = conn.execute("SELECT id FROM opportunities WHERE run_id='ws-1'").fetchone()["id"]

    assert update_opportunity_status(conn, opp_id, "under_review") is True
    row = conn.execute("SELECT status FROM opportunities WHERE id=?", (opp_id,)).fetchone()
    assert row["status"] == "under_review"
    conn.close()


def test_update_status_records_event(tmp_path):
    conn = _tmp_conn(tmp_path)
    _save_one(conn, run_id="ws-2")
    opp_id = conn.execute("SELECT id FROM opportunities WHERE run_id='ws-2'").fetchone()["id"]

    update_opportunity_status(conn, opp_id, "prioritized", note="Strong signal")
    event = conn.execute(
        "SELECT * FROM workflow_events WHERE opp_id=?", (opp_id,)
    ).fetchone()
    assert event["from_status"] == "discovered"
    assert event["to_status"] == "prioritized"
    assert event["note"] == "Strong signal"
    conn.close()


def test_update_status_returns_false_for_unknown_id(tmp_path):
    conn = _tmp_conn(tmp_path)
    result = update_opportunity_status(conn, 99999, "rejected")
    assert result is False
    conn.close()


def test_update_status_raises_for_invalid_status(tmp_path):
    conn = _tmp_conn(tmp_path)
    _save_one(conn, run_id="ws-3")
    opp_id = conn.execute("SELECT id FROM opportunities WHERE run_id='ws-3'").fetchone()["id"]
    with pytest.raises(ValueError, match="Invalid status"):
        update_opportunity_status(conn, opp_id, "wont_happen")
    conn.close()


# ── list_opportunities ─────────────────────────────────────────────────────────

def test_list_opportunities_returns_all(tmp_path):
    conn = _tmp_conn(tmp_path)
    _save_one(conn, run_id="lo-1", city="Vancouver", industry="Construction")
    rows = list_opportunities(conn)
    assert len(rows) >= 1
    conn.close()


def test_list_opportunities_filters_by_status(tmp_path):
    conn = _tmp_conn(tmp_path)
    _save_one(conn, run_id="lo-2")
    opp_id = conn.execute("SELECT id FROM opportunities WHERE run_id='lo-2'").fetchone()["id"]
    update_opportunity_status(conn, opp_id, "prioritized")

    prioritized = list_opportunities(conn, status="prioritized")
    discovered = list_opportunities(conn, status="discovered")
    assert any(r["id"] == opp_id for r in prioritized)
    assert not any(r["id"] == opp_id for r in discovered)
    conn.close()


def test_list_opportunities_filters_by_city_industry(tmp_path):
    conn = _tmp_conn(tmp_path)
    _save_one(conn, run_id="lo-3", city="Toronto", industry="Retail")
    _save_one(conn, run_id="lo-4", city="Vancouver", industry="Construction")

    toronto_rows = list_opportunities(conn, city="Toronto", industry="Retail")
    assert all(r["city"] == "Toronto" for r in toronto_rows)
    conn.close()


# ── get_trend_data ─────────────────────────────────────────────────────────────

def test_get_trend_data_empty(tmp_path):
    conn = _tmp_conn(tmp_path)
    result = get_trend_data(conn, "Vancouver", "Construction")
    assert result == []
    conn.close()


def test_get_trend_data_single_run(tmp_path):
    conn = _tmp_conn(tmp_path)
    _save_one(conn, run_id="td-1", city="Vancouver", industry="Construction")
    result = get_trend_data(conn, "Vancouver", "Construction")
    assert len(result) >= 1
    assert result[0]["trend"] == "single"
    conn.close()


def test_get_trend_data_trend_direction(tmp_path):
    """Opportunity appearing twice with rising pain is classified as 'rising'."""
    conn = _tmp_conn(tmp_path)
    for run_id, ts, pain in [
        ("td-rising-a", "2024-01-01T00:00:00Z", 4.0),
        ("td-rising-b", "2024-06-01T00:00:00Z", 8.5),
    ]:
        strat = _make_strategy(pain=pain)
        save_run(
            conn=conn, run_id=run_id, city="Vancouver", industry="Construction",
            strategy=strat, headlines=[], jobs=[], fetch_status={},
            run_metadata={"started_at_iso": ts, "deterministic": False},
            strategy_mode="mock",
        )
    result = get_trend_data(conn, "Vancouver", "Construction", limit_runs=5)
    assert len(result) == 1
    assert result[0]["trend"] == "rising"
    # New quality fields must be present
    assert "avg_confidence" in result[0]
    assert "trend_quality" in result[0]
    assert "history_summary" in result[0]
    conn.close()


def test_get_trend_data_stable(tmp_path):
    conn = _tmp_conn(tmp_path)
    for run_id, ts in [("td-s-a", "2024-01-01T00:00:00Z"), ("td-s-b", "2024-06-01T00:00:00Z")]:
        strat = _make_strategy(pain=5.0)
        save_run(
            conn=conn, run_id=run_id, city="Vancouver", industry="Construction",
            strategy=strat, headlines=[], jobs=[], fetch_status={},
            run_metadata={"started_at_iso": ts, "deterministic": False},
            strategy_mode="mock",
        )
    result = get_trend_data(conn, "Vancouver", "Construction")
    assert result[0]["trend"] == "stable"
    conn.close()


# ── opp CLI commands ───────────────────────────────────────────────────────────

def test_cmd_opp_list_no_data(tmp_path):
    db_path = tmp_path / "empty.db"
    result = subprocess.run(
        [sys.executable, "-m", "marketscout", "opp", "list"],
        capture_output=True, text=True,
        env=_src_env(tmp_path, MARKETSCOUT_DB_PATH=str(db_path)),
    )
    assert result.returncode == 0, result.stderr
    assert "No opportunities found" in result.stdout


def test_cmd_opp_set_invalid_status(tmp_path):
    db_path = tmp_path / "empty.db"
    result = subprocess.run(
        [sys.executable, "-m", "marketscout", "opp", "set", "1", "--status", "flying"],
        capture_output=True, text=True,
        env=_src_env(tmp_path, MARKETSCOUT_DB_PATH=str(db_path)),
    )
    assert result.returncode != 0


# ── get_db_path ────────────────────────────────────────────────────────────────

def test_get_db_path_env_override(tmp_path, monkeypatch):
    custom = str(tmp_path / "custom.db")
    monkeypatch.setenv("MARKETSCOUT_DB_PATH", custom)
    assert str(get_db_path()) == custom
