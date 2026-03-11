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
    compare_runs,
    generate_run_id,
    get_connection,
    get_db_path,
    init_db,
    list_runs,
    save_run,
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
):
    """Build a minimal StrategyOutput-compatible mock."""
    opp = SimpleNamespace(
        title="Test Opp",
        problem="Test problem",
        ai_category="Automation",
        pain_score=pain,
        automation_potential=6.0,
        roi_signal=5.0,
        confidence=0.8,
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


# ── get_db_path ────────────────────────────────────────────────────────────────

def test_get_db_path_env_override(tmp_path, monkeypatch):
    custom = str(tmp_path / "custom.db")
    monkeypatch.setenv("MARKETSCOUT_DB_PATH", custom)
    assert str(get_db_path()) == custom
