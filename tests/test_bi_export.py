"""Tests for Phase 6: BI export layer.

Covers:
  - All three CSV files are created
  - dim_opportunities: columns, data types, urgency_score derivation, opportunity_type derivation
  - fact_leads: JSON unnested to multiple rows, join key preserved
  - fact_actions: JSON unnested with action_index, join key preserved
  - Opportunities with no leads / no actions produce zero rows in fact tables
  - Malformed JSON is handled gracefully (no crash, rows skipped)
  - run_id filter: only rows for the requested run are exported
  - Empty run (no opportunities) produces valid empty CSVs
  - FileNotFoundError raised for missing DB
  - Deterministic output (same input → same CSV content)
  - _urgency_score and _opportunity_type helper coverage
"""

from __future__ import annotations

import csv
import json
import sqlite3
import tempfile
from pathlib import Path

import pytest

from marketscout.bi_export import (
    DIM_OPPORTUNITIES_FIELDS,
    FACT_ACTIONS_FIELDS,
    FACT_LEADS_FIELDS,
    _opportunity_type,
    _urgency_score,
    export_to_bi,
)
from marketscout.db import get_connection, save_run


# ── Test fixtures ─────────────────────────────────────────────────────────────

def _make_strategy(
    *,
    run_id: str = "test-run-1",
    title: str = "Labor shortages",
    pain_score: float = 7.0,
    roi_signal: float = 5.0,
    confidence: float = 0.6,
    ai_category: str = "Operational efficiency",
    recommendation: str = "pursue_now",
    trend_key: str = "operational_efficiency::labor_shortages",
    suggested_actions: list[str] | None = None,
    leads: list[dict] | None = None,
    n_padded: int = 4,
):
    """Build a minimal StrategyOutput-like object via generate_mock_strategy."""
    from marketscout.brain.schema import (
        BusinessCase, DataQuality, EvidenceItem, Lead, OpportunityItem,
        ScoreBreakdown, SignalsUsed, StrategyOutput,
    )

    actions = suggested_actions if suggested_actions is not None else [
        "Pull top companies from leads.csv",
        "Book 3 discovery calls this sprint",
    ]
    raw_leads = leads if leads is not None else [
        {
            "company_name": "BuildCo",
            "reason": "Hiring for Labor Coordinator",
            "signal_type": "job",
            "signal_reference": "Labor Coordinator",
            "priority_score": 3.0,
        },
        {
            "company_name": "AnotherCo",
            "reason": "Hiring for Labor Manager",
            "signal_type": "job",
            "signal_reference": "Labor Manager",
            "priority_score": 2.0,
        },
    ]
    lead_objs = [Lead(**l) for l in raw_leads]

    opp = OpportunityItem(
        title=title,
        problem="Labor shortages and wage pressure",
        ai_category=ai_category,
        evidence=[EvidenceItem(title="h", link="http://x.com/1", source="headline")],
        pain_score=pain_score,
        automation_potential=5.0,
        roi_signal=roi_signal,
        confidence=confidence,
        business_case=BusinessCase(savings_range_annual="$50k–$200k"),
        score_breakdown=ScoreBreakdown(signal_frequency=0.5, source_diversity=0.3, job_role_density=0.2),
        trend_key=trend_key,
        recommendation=recommendation,
        opportunity_type="operational",
        suggested_actions=actions,
        leads=lead_objs,
    )
    padded = [
        OpportunityItem(
            title=f"Pad {i}",
            problem=f"Pad {i}",
            ai_category="Operational efficiency",
            evidence=[EvidenceItem(title="p", link=f"http://x.com/p{i}", source="headline")],
            pain_score=3.0,
            automation_potential=5.0,
            roi_signal=4.0,
            confidence=0.3,
            business_case=BusinessCase(savings_range_annual="$30k–$100k"),
            score_breakdown=ScoreBreakdown(signal_frequency=1/3, source_diversity=1/3, job_role_density=1/3),
            trend_key=f"padded::pad_{i}",
            recommendation="deprioritize",
            opportunity_type="operational",
            is_padded=True,
            support_level="weak",
            suggested_actions=["Do not invest resources yet — signal quality is insufficient to justify action"],
        )
        for i in range(n_padded)
    ]
    return StrategyOutput(
        city="Vancouver",
        industry="Construction",
        opportunity_map=[opp] + padded,
        signals_used=SignalsUsed(headlines_count=3, jobs_count=2),
        data_quality=DataQuality(freshness_window_days=7, coverage_score=0.7, source_mix_score=0.6),
    )


def _save(conn, run_id: str, strategy):
    save_run(
        conn, run_id, "Vancouver", "Construction", strategy,
        [], [], {"headlines": {}, "jobs": {}},
        {"started_at_iso": "2024-01-01T00:00:00Z", "deterministic": False},
        "deterministic",
    )


def _setup_db(run_id: str = "test-run-1", **strategy_kwargs):
    """Create a temp DB, save a run, return (db_path, export_dir)."""
    tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp_db.close()
    tmp_export = tempfile.mkdtemp()
    conn = get_connection(Path(tmp_db.name))
    strategy = _make_strategy(run_id=run_id, **strategy_kwargs)
    _save(conn, run_id, strategy)
    conn.close()
    return Path(tmp_db.name), Path(tmp_export)


def _read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


# ── File creation ─────────────────────────────────────────────────────────────

def test_export_creates_all_three_files():
    db, export_dir = _setup_db()
    paths = export_to_bi(str(db), str(export_dir), "test-run-1")
    assert paths["dim_opportunities"].exists()
    assert paths["fact_leads"].exists()
    assert paths["fact_actions"].exists()


def test_export_returns_correct_path_keys():
    db, export_dir = _setup_db()
    paths = export_to_bi(str(db), str(export_dir), "test-run-1")
    assert set(paths.keys()) == {"dim_opportunities", "fact_leads", "fact_actions"}


def test_export_creates_export_dir_if_missing():
    db, _ = _setup_db()
    new_dir = Path(tempfile.mkdtemp()) / "nested" / "bi"
    export_to_bi(str(db), str(new_dir), "test-run-1")
    assert new_dir.is_dir()


# ── dim_opportunities ─────────────────────────────────────────────────────────

def test_dim_opportunities_has_correct_headers():
    db, export_dir = _setup_db()
    paths = export_to_bi(str(db), str(export_dir), "test-run-1")
    rows = _read_csv(paths["dim_opportunities"])
    assert rows  # not empty
    assert list(rows[0].keys()) == DIM_OPPORTUNITIES_FIELDS


def test_dim_opportunities_row_count():
    """One row per opportunity in the run (1 real + 4 padded = 5)."""
    db, export_dir = _setup_db()
    paths = export_to_bi(str(db), str(export_dir), "test-run-1")
    rows = _read_csv(paths["dim_opportunities"])
    assert len(rows) == 5


def test_dim_opportunities_run_id_populated():
    db, export_dir = _setup_db(run_id="my-run-abc")
    paths = export_to_bi(str(db), str(export_dir), "my-run-abc")
    rows = _read_csv(paths["dim_opportunities"])
    for row in rows:
        assert row["run_id"] == "my-run-abc"


def test_dim_opportunities_trend_key_populated():
    db, export_dir = _setup_db(trend_key="operational_efficiency::labor_shortages")
    paths = export_to_bi(str(db), str(export_dir), "test-run-1")
    rows = _read_csv(paths["dim_opportunities"])
    trend_keys = [r["trend_key"] for r in rows]
    assert "operational_efficiency::labor_shortages" in trend_keys


def test_dim_opportunities_urgency_score_derivation():
    """urgency_score = round(confidence × pain_score, 2)."""
    db, export_dir = _setup_db(pain_score=8.0, confidence=0.75)
    paths = export_to_bi(str(db), str(export_dir), "test-run-1")
    rows = _read_csv(paths["dim_opportunities"])
    labor_row = next(r for r in rows if r["title"] == "Labor shortages")
    assert float(labor_row["urgency_score"]) == pytest.approx(6.0)


def test_dim_opportunities_urgency_score_zero_confidence():
    """confidence=0 → urgency_score=0."""
    db, export_dir = _setup_db(pain_score=9.0, confidence=0.0)
    paths = export_to_bi(str(db), str(export_dir), "test-run-1")
    rows = _read_csv(paths["dim_opportunities"])
    labor_row = next(r for r in rows if r["title"] == "Labor shortages")
    assert float(labor_row["urgency_score"]) == pytest.approx(0.0)


def test_dim_opportunities_opportunity_type_derived_from_ai_category():
    db, export_dir = _setup_db(ai_category="Market entry")
    paths = export_to_bi(str(db), str(export_dir), "test-run-1")
    rows = _read_csv(paths["dim_opportunities"])
    labor_row = next(r for r in rows if r["title"] == "Labor shortages")
    assert labor_row["opportunity_type"] == "strategic"


def test_dim_opportunities_compliance_type():
    db, export_dir = _setup_db(ai_category="Regulatory & permits")
    paths = export_to_bi(str(db), str(export_dir), "test-run-1")
    rows = _read_csv(paths["dim_opportunities"])
    labor_row = next(r for r in rows if r["title"] == "Labor shortages")
    assert labor_row["opportunity_type"] == "compliance"


def test_dim_opportunities_numeric_fields_are_parseable():
    db, export_dir = _setup_db(pain_score=7.5, roi_signal=6.0, confidence=0.65)
    paths = export_to_bi(str(db), str(export_dir), "test-run-1")
    rows = _read_csv(paths["dim_opportunities"])
    labor_row = next(r for r in rows if r["title"] == "Labor shortages")
    assert float(labor_row["pain_score"]) == pytest.approx(7.5)
    assert float(labor_row["roi_signal"]) == pytest.approx(6.0)
    assert float(labor_row["confidence"]) == pytest.approx(0.65)


# ── fact_leads ────────────────────────────────────────────────────────────────

def test_fact_leads_has_correct_headers():
    db, export_dir = _setup_db()
    paths = export_to_bi(str(db), str(export_dir), "test-run-1")
    rows = _read_csv(paths["fact_leads"])
    assert rows
    assert list(rows[0].keys()) == FACT_LEADS_FIELDS


def test_fact_leads_unnested_two_leads_produce_two_rows():
    """Opportunity with 2 leads → 2 rows in fact_leads."""
    db, export_dir = _setup_db()
    paths = export_to_bi(str(db), str(export_dir), "test-run-1")
    rows = _read_csv(paths["fact_leads"])
    labor_rows = [r for r in rows if r["trend_key"] == "operational_efficiency::labor_shortages"]
    assert len(labor_rows) == 2


def test_fact_leads_company_names_correct():
    db, export_dir = _setup_db()
    paths = export_to_bi(str(db), str(export_dir), "test-run-1")
    rows = _read_csv(paths["fact_leads"])
    labor_rows = [r for r in rows if r["trend_key"] == "operational_efficiency::labor_shortages"]
    companies = {r["company_name"] for r in labor_rows}
    assert companies == {"BuildCo", "AnotherCo"}


def test_fact_leads_signal_type_preserved():
    db, export_dir = _setup_db()
    paths = export_to_bi(str(db), str(export_dir), "test-run-1")
    rows = _read_csv(paths["fact_leads"])
    for r in rows:
        if r["company_name"]:
            assert r["signal_type"] in ("job", "news")


def test_fact_leads_priority_score_is_numeric():
    db, export_dir = _setup_db()
    paths = export_to_bi(str(db), str(export_dir), "test-run-1")
    rows = _read_csv(paths["fact_leads"])
    for r in rows:
        assert 0.0 <= float(r["priority_score"]) <= 10.0


def test_fact_leads_join_key_matches_dim():
    """Every (run_id, trend_key) in fact_leads must exist in dim_opportunities."""
    db, export_dir = _setup_db()
    paths = export_to_bi(str(db), str(export_dir), "test-run-1")
    dim_keys = {(r["run_id"], r["trend_key"]) for r in _read_csv(paths["dim_opportunities"])}
    lead_keys = {(r["run_id"], r["trend_key"]) for r in _read_csv(paths["fact_leads"])}
    assert lead_keys.issubset(dim_keys)


def test_fact_leads_no_leads_produces_no_rows_for_that_opportunity():
    """Opportunity with empty leads list → no rows in fact_leads for its trend_key."""
    db, export_dir = _setup_db(leads=[])
    paths = export_to_bi(str(db), str(export_dir), "test-run-1")
    rows = _read_csv(paths["fact_leads"])
    labor_rows = [r for r in rows if r["trend_key"] == "operational_efficiency::labor_shortages"]
    assert labor_rows == []


# ── fact_actions ──────────────────────────────────────────────────────────────

def test_fact_actions_has_correct_headers():
    db, export_dir = _setup_db()
    paths = export_to_bi(str(db), str(export_dir), "test-run-1")
    rows = _read_csv(paths["fact_actions"])
    assert rows
    assert list(rows[0].keys()) == FACT_ACTIONS_FIELDS


def test_fact_actions_unnested_two_actions_produce_two_rows():
    """Opportunity with 2 actions → 2 rows in fact_actions."""
    db, export_dir = _setup_db(
        suggested_actions=["Action A", "Action B"]
    )
    paths = export_to_bi(str(db), str(export_dir), "test-run-1")
    rows = _read_csv(paths["fact_actions"])
    labor_rows = [r for r in rows if r["trend_key"] == "operational_efficiency::labor_shortages"]
    assert len(labor_rows) == 2


def test_fact_actions_action_index_is_zero_based():
    db, export_dir = _setup_db(suggested_actions=["First", "Second", "Third"])
    paths = export_to_bi(str(db), str(export_dir), "test-run-1")
    rows = _read_csv(paths["fact_actions"])
    labor_rows = sorted(
        [r for r in rows if r["trend_key"] == "operational_efficiency::labor_shortages"],
        key=lambda r: int(r["action_index"]),
    )
    assert [r["action_index"] for r in labor_rows] == ["0", "1", "2"]
    assert [r["action_text"] for r in labor_rows] == ["First", "Second", "Third"]


def test_fact_actions_join_key_matches_dim():
    db, export_dir = _setup_db()
    paths = export_to_bi(str(db), str(export_dir), "test-run-1")
    dim_keys = {(r["run_id"], r["trend_key"]) for r in _read_csv(paths["dim_opportunities"])}
    action_keys = {(r["run_id"], r["trend_key"]) for r in _read_csv(paths["fact_actions"])}
    assert action_keys.issubset(dim_keys)


def test_fact_actions_no_actions_produces_no_rows_for_that_opportunity():
    db, export_dir = _setup_db(suggested_actions=[])
    paths = export_to_bi(str(db), str(export_dir), "test-run-1")
    rows = _read_csv(paths["fact_actions"])
    labor_rows = [r for r in rows if r["trend_key"] == "operational_efficiency::labor_shortages"]
    assert labor_rows == []


# ── Malformed JSON handling ────────────────────────────────────────────────────

def test_malformed_leads_json_produces_no_rows_no_crash():
    """If the leads column contains invalid JSON, no crash and no rows for that opp."""
    tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp_db.close()
    tmp_export = tempfile.mkdtemp()
    conn = get_connection(Path(tmp_db.name))
    strategy = _make_strategy(run_id="corrupt-run")
    _save(conn, "corrupt-run", strategy)
    # Corrupt the leads JSON for the first opportunity
    conn.execute(
        "UPDATE opportunities SET leads = 'NOT VALID JSON' WHERE run_id = ? AND title = 'Labor shortages'",
        ("corrupt-run",),
    )
    conn.commit()
    conn.close()
    paths = export_to_bi(tmp_db.name, tmp_export, "corrupt-run")
    rows = _read_csv(paths["fact_leads"])
    labor_rows = [r for r in rows if r["trend_key"] == "operational_efficiency::labor_shortages"]
    assert labor_rows == []  # malformed JSON → silently skipped


def test_malformed_actions_json_produces_no_rows_no_crash():
    tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp_db.close()
    tmp_export = tempfile.mkdtemp()
    conn = get_connection(Path(tmp_db.name))
    strategy = _make_strategy(run_id="corrupt-run-2")
    _save(conn, "corrupt-run-2", strategy)
    conn.execute(
        "UPDATE opportunities SET suggested_actions = '{broken' WHERE run_id = ? AND title = 'Labor shortages'",
        ("corrupt-run-2",),
    )
    conn.commit()
    conn.close()
    paths = export_to_bi(tmp_db.name, tmp_export, "corrupt-run-2")
    rows = _read_csv(paths["fact_actions"])
    labor_rows = [r for r in rows if r["trend_key"] == "operational_efficiency::labor_shortages"]
    assert labor_rows == []


# ── run_id filter ─────────────────────────────────────────────────────────────

def test_run_id_filter_only_exports_requested_run():
    """Two runs in the DB; export only returns rows for the requested run_id."""
    tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp_db.close()
    tmp_export = tempfile.mkdtemp()
    conn = get_connection(Path(tmp_db.name))
    _save(conn, "run-A", _make_strategy(run_id="run-A", title="Opp A"))
    _save(conn, "run-B", _make_strategy(run_id="run-B", title="Opp B"))
    conn.close()

    paths = export_to_bi(tmp_db.name, tmp_export, "run-A")
    rows = _read_csv(paths["dim_opportunities"])
    assert all(r["run_id"] == "run-A" for r in rows)
    titles = [r["title"] for r in rows]
    assert "Opp A" in titles
    assert "Opp B" not in titles


# ── Empty run ─────────────────────────────────────────────────────────────────

def test_empty_run_produces_valid_empty_csvs():
    """run_id with no opportunities → valid CSV files with headers only."""
    db, export_dir = _setup_db()
    paths = export_to_bi(str(db), str(export_dir), "nonexistent-run-id")
    for key in ("dim_opportunities", "fact_leads", "fact_actions"):
        rows = _read_csv(paths[key])
        assert rows == []  # header present, no data rows


# ── Error handling ────────────────────────────────────────────────────────────

def test_missing_db_raises_file_not_found():
    with pytest.raises(FileNotFoundError):
        export_to_bi("/nonexistent/path/to.db", "/tmp/bi", "any-run-id")


# ── Determinism ───────────────────────────────────────────────────────────────

def test_export_is_deterministic():
    """Same DB and run_id → identical CSV output on every call."""
    db, export_dir = _setup_db()
    paths1 = export_to_bi(str(db), str(export_dir), "test-run-1")
    paths2 = export_to_bi(str(db), str(export_dir), "test-run-1")
    for key in ("dim_opportunities", "fact_leads", "fact_actions"):
        assert paths1[key].read_text() == paths2[key].read_text()


# ── Helper unit tests ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("ai_category,expected", [
    ("Operational efficiency", "operational"),
    ("Cost reduction",         "operational"),
    ("Risk mitigation",        "compliance"),
    ("Regulatory & permits",   "compliance"),
    ("Market entry",           "strategic"),
    ("Growth and scale",       "strategic"),
    ("Partnership and M&A",    "strategic"),
    ("Unknown category",       "operational"),  # fallback
    ("",                       "operational"),  # empty fallback
])
def test_opportunity_type_mapping(ai_category, expected):
    assert _opportunity_type(ai_category) == expected


@pytest.mark.parametrize("confidence,pain_score,expected", [
    (0.6,  7.0,  4.2),
    (0.75, 8.0,  6.0),
    (0.0,  9.0,  0.0),
    (1.0,  10.0, 10.0),
    (0.5,  3.0,  1.5),
])
def test_urgency_score_derivation(confidence, pain_score, expected):
    assert _urgency_score(confidence, pain_score) == pytest.approx(expected, abs=1e-9)
