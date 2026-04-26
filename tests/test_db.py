"""Gold layer tests: init_db, write_gold roundtrip, idempotency, read-only engine."""

from __future__ import annotations

import sqlite3

import pytest
from sqlalchemy import text

from marketscout.backend.schema import (
    BusinessCase,
    EvidenceItem,
    OpportunityItem,
    ScoreBreakdown,
)
from marketscout.db import get_readonly_engine, init_db, write_gold


# ── Fixtures ──────────────────────────────────────────────────────────────────

_SAMPLE_SIGNALS: list[dict] = [
    {
        "title": "Labor shortage hits Vancouver construction",
        "link": "https://example.com/1",
        "source": "CBC",
        "published": "Mon, 01 Jan 2024 00:00:00 +0000",
        "company": "",
    },
    {
        "title": "Site Coordinator",
        "link": "https://example.com/2",
        "source": "adzuna",
        "published": "Tue, 02 Jan 2024 00:00:00 +0000",
        "company": "BuildCo Inc.",
    },
]


def _make_opportunity(title: str = "Labor gap") -> OpportunityItem:
    return OpportunityItem(
        title=title,
        problem="Labor shortage and wage pressure in construction",
        ai_category="Operational efficiency",
        evidence=[
            EvidenceItem(
                title="Labor shortage hits Vancouver construction",
                link="https://example.com/1",
                source="headline",
            ),
            EvidenceItem(
                title="Site Coordinator",
                link="https://example.com/2",
                source="job",
            ),
        ],
        pain_score=7.5,
        automation_potential=6.0,
        roi_signal=8.0,
        confidence=0.65,
        business_case=BusinessCase(
            savings_range_annual="$80k–$200k",
            assumptions=["10% workforce reduction"],
        ),
        score_breakdown=ScoreBreakdown(
            signal_frequency=0.5,
            source_diversity=0.3,
            job_role_density=0.2,
        ),
    )


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_init_db_creates_all_four_tables(tmp_path: pytest.fixture) -> None:
    """init_db must create dim_runs, dim_opportunities, dim_signals, fact_leads."""
    db_path = tmp_path / "test.db"
    init_db(db_path)

    conn = sqlite3.connect(str(db_path))
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    conn.close()

    assert "dim_runs" in tables
    assert "dim_opportunities" in tables
    assert "dim_signals" in tables
    assert "fact_leads" in tables


def test_write_gold_roundtrip(tmp_path: pytest.fixture) -> None:
    """write_gold writes exactly the expected number of rows for one run."""
    db_path = tmp_path / "test.db"
    init_db(db_path)

    opps = [_make_opportunity("Labor gap"), _make_opportunity("Permit delays")]
    write_gold("run-001", "Vancouver", "Construction", opps, _SAMPLE_SIGNALS, db_path=db_path)

    conn = sqlite3.connect(str(db_path))
    run_count = conn.execute("SELECT COUNT(*) FROM dim_runs").fetchone()[0]
    opp_count = conn.execute("SELECT COUNT(*) FROM dim_opportunities").fetchone()[0]
    sig_count = conn.execute("SELECT COUNT(*) FROM dim_signals").fetchone()[0]
    lead_count = conn.execute("SELECT COUNT(*) FROM fact_leads").fetchone()[0]
    conn.close()

    assert run_count == 1
    assert opp_count == 2                    # two opportunities
    assert sig_count == 2                    # two raw signals
    assert lead_count == 4                   # 2 evidence items × 2 opportunities


def test_write_gold_idempotent(tmp_path: pytest.fixture) -> None:
    """Calling write_gold twice with the same run_id must not duplicate rows."""
    db_path = tmp_path / "test.db"
    init_db(db_path)

    opps = [_make_opportunity()]
    write_gold("run-002", "Toronto", "Retail", opps, _SAMPLE_SIGNALS, db_path=db_path)
    write_gold("run-002", "Toronto", "Retail", opps, _SAMPLE_SIGNALS, db_path=db_path)

    conn = sqlite3.connect(str(db_path))
    assert conn.execute("SELECT COUNT(*) FROM dim_runs").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM dim_opportunities").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM dim_signals").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM fact_leads").fetchone()[0] == 2
    conn.close()


def test_get_readonly_engine_rejects_write(tmp_path: pytest.fixture) -> None:
    """get_readonly_engine must raise an exception on any write attempt."""
    db_path = tmp_path / "test.db"
    init_db(db_path)

    engine = get_readonly_engine(db_path)
    with pytest.raises(Exception):
        with engine.connect() as conn:
            conn.execute(
                text("INSERT INTO dim_runs (id, city, industry) VALUES ('x', 'x', 'x')")
            )
    engine.dispose()
