"""
Trend quality tests: quality-aware trending, trend_quality classification,
compare aggregation quality fields, history_summary grounding.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from marketscout.db import (
    _classify_trend_quality,
    compare_runs,
    get_connection,
    get_trend_data,
    save_run,
)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _tmp_conn(tmp_path: Path):
    db_path = tmp_path / "test_trend.db"
    return get_connection(db_path)


def _make_opp(
    title: str = "Test Opp",
    pain: float = 7.0,
    confidence: float = 0.7,
    support_level: str = "moderate",
    is_padded: bool = False,
    signal_age_days_avg: float | None = 10.0,
    unique_sources_count: int = 2,
):
    return SimpleNamespace(
        title=title,
        problem=title,
        ai_category="Operational efficiency",
        pain_score=pain,
        automation_potential=6.0,
        roi_signal=5.0,
        confidence=confidence,
        support_level=support_level,
        is_padded=is_padded,
        signal_age_days_avg=signal_age_days_avg,
        unique_sources_count=unique_sources_count,
    )


def _make_strategy(opps: list, city: str = "Vancouver", industry: str = "Construction"):
    dq = SimpleNamespace(coverage_score=0.75, freshness_window_days=7, source_mix_score=0.6)
    su = SimpleNamespace(headlines_count=5, jobs_count=5)
    return SimpleNamespace(city=city, industry=industry, data_quality=dq, signals_used=su, opportunity_map=opps)


def _save_run(conn, run_id: str, ts: str, opps: list, city: str = "Vancouver", industry: str = "Construction"):
    strategy = _make_strategy(opps, city=city, industry=industry)
    save_run(
        conn=conn,
        run_id=run_id,
        city=city,
        industry=industry,
        strategy=strategy,
        headlines=[],
        jobs=[],
        fetch_status={},
        run_metadata={"started_at_iso": ts, "deterministic": False},
        strategy_mode="mock",
    )


# ── _classify_trend_quality unit tests ───────────────────────────────────────


def test_classify_investable_strong_repeated() -> None:
    """Repeated strong support, stable, high confidence → investable."""
    result = _classify_trend_quality(
        appearances=3,
        trend="stable",
        avg_confidence=0.75,
        padded_count=0,
        strong_count=2,
    )
    assert result == "investable"


def test_classify_investable_rising_strong() -> None:
    result = _classify_trend_quality(
        appearances=2,
        trend="rising",
        avg_confidence=0.65,
        padded_count=0,
        strong_count=2,
    )
    assert result == "investable"


def test_classify_noise_majority_padded() -> None:
    """More than half appearances padded → noise."""
    result = _classify_trend_quality(
        appearances=3,
        trend="stable",
        avg_confidence=0.3,
        padded_count=2,
        strong_count=0,
    )
    assert result == "noise"


def test_classify_noise_all_padded() -> None:
    result = _classify_trend_quality(
        appearances=4,
        trend="stable",
        avg_confidence=0.3,
        padded_count=4,
        strong_count=0,
    )
    assert result == "noise"


def test_classify_exactly_half_padded_is_noise() -> None:
    """Exactly half padded (2/4) should also be noise."""
    result = _classify_trend_quality(
        appearances=4,
        trend="stable",
        avg_confidence=0.4,
        padded_count=2,
        strong_count=0,
    )
    assert result == "noise"


def test_classify_declining_falling_trend() -> None:
    """Falling pain trend → declining, even if not padded."""
    result = _classify_trend_quality(
        appearances=3,
        trend="falling",
        avg_confidence=0.6,
        padded_count=0,
        strong_count=2,
    )
    assert result == "declining"


def test_classify_emerging_single_strong() -> None:
    """Single appearance with strong support → emerging."""
    result = _classify_trend_quality(
        appearances=1,
        trend="single",
        avg_confidence=0.8,
        padded_count=0,
        strong_count=1,
    )
    assert result == "emerging"


def test_classify_monitor_single_not_strong() -> None:
    """Single appearance, no strong support → monitor."""
    result = _classify_trend_quality(
        appearances=1,
        trend="single",
        avg_confidence=0.4,
        padded_count=0,
        strong_count=0,
    )
    assert result == "monitor"


def test_classify_monitor_repeated_low_confidence() -> None:
    """Repeated but confidence too low for investable → monitor."""
    result = _classify_trend_quality(
        appearances=3,
        trend="stable",
        avg_confidence=0.3,     # below 0.5 threshold
        padded_count=0,
        strong_count=3,
    )
    assert result == "monitor"


def test_classify_monitor_repeated_few_strong() -> None:
    """Repeated but strong appearances are minority → monitor."""
    result = _classify_trend_quality(
        appearances=4,
        trend="stable",
        avg_confidence=0.6,
        padded_count=0,
        strong_count=1,  # only 1/4 strong — below majority threshold
    )
    assert result == "monitor"


# ── Trend data integration: repeated strong → investable ─────────────────────


def test_trend_data_repeated_strong_is_investable(tmp_path: Path) -> None:
    """
    An opportunity appearing in 3 runs with support_level='strong' each time
    should produce trend_quality='investable'.
    """
    conn = _tmp_conn(tmp_path)
    for i, ts in enumerate([
        "2024-01-01T00:00:00Z",
        "2024-03-01T00:00:00Z",
        "2024-06-01T00:00:00Z",
    ]):
        _save_run(conn, f"strong-{i}", ts, [
            _make_opp(title="Labor shortage", pain=7.5, confidence=0.75, support_level="strong")
        ])
    result = get_trend_data(conn, "Vancouver", "Construction", limit_runs=5)
    opp = next(r for r in result if "Labor" in r["title"])
    assert opp["strong_count"] == 3
    assert opp["trend_quality"] == "investable"
    conn.close()


def test_trend_data_repeated_padded_is_noise(tmp_path: Path) -> None:
    """
    An opportunity appearing in 3 runs as padded should produce trend_quality='noise'.
    """
    conn = _tmp_conn(tmp_path)
    for i, ts in enumerate([
        "2024-01-01T00:00:00Z",
        "2024-03-01T00:00:00Z",
        "2024-06-01T00:00:00Z",
    ]):
        _save_run(conn, f"padded-{i}", ts, [
            _make_opp(title="Market dynamics", pain=3.0, confidence=0.3, support_level="weak", is_padded=True)
        ])
    result = get_trend_data(conn, "Vancouver", "Construction", limit_runs=5)
    opp = next(r for r in result if "Market" in r["title"])
    assert opp["padded_count"] == 3
    assert opp["trend_quality"] == "noise"
    conn.close()


def test_trend_data_single_strong_is_emerging(tmp_path: Path) -> None:
    """Single appearance with strong support → trend_quality='emerging'."""
    conn = _tmp_conn(tmp_path)
    _save_run(conn, "emerging-1", "2024-06-01T00:00:00Z", [
        _make_opp(title="AI workflow surge", pain=8.0, confidence=0.85, support_level="strong")
    ])
    result = get_trend_data(conn, "Vancouver", "Construction", limit_runs=5)
    opp = next(r for r in result if "AI" in r["title"])
    assert opp["appearances"] == 1
    assert opp["trend_quality"] == "emerging"
    conn.close()


def test_trend_data_falling_pain_is_declining(tmp_path: Path) -> None:
    """Opportunity with sharply falling pain score → trend_quality='declining'."""
    conn = _tmp_conn(tmp_path)
    for run_id, ts, pain in [
        ("falling-a", "2024-01-01T00:00:00Z", 8.5),
        ("falling-b", "2024-06-01T00:00:00Z", 4.0),
    ]:
        _save_run(conn, run_id, ts, [
            _make_opp(title="Supply chain tension", pain=pain, confidence=0.6, support_level="moderate")
        ])
    result = get_trend_data(conn, "Vancouver", "Construction", limit_runs=5)
    opp = next(r for r in result if "Supply" in r["title"])
    assert opp["trend"] == "falling"
    assert opp["trend_quality"] == "declining"
    conn.close()


def test_trend_data_mixed_quality_is_monitor(tmp_path: Path) -> None:
    """Opportunity with mixed quality across runs → trend_quality='monitor'."""
    conn = _tmp_conn(tmp_path)
    qualities = [("moderate", False), ("weak", False), ("moderate", False)]
    for i, (ts, (support, padded)) in enumerate(zip(
        ["2024-01-01T00:00:00Z", "2024-03-01T00:00:00Z", "2024-06-01T00:00:00Z"],
        qualities,
    )):
        _save_run(conn, f"mixed-{i}", ts, [
            _make_opp(title="Permit delays", pain=5.5, confidence=0.45, support_level=support, is_padded=padded)
        ])
    result = get_trend_data(conn, "Vancouver", "Construction", limit_runs=5)
    opp = next(r for r in result if "Permit" in r["title"])
    assert opp["trend_quality"] == "monitor"
    conn.close()


# ── Trend data: quality fields present ───────────────────────────────────────


def test_trend_data_has_all_quality_fields(tmp_path: Path) -> None:
    """Every trend entry must carry the new quality fields."""
    conn = _tmp_conn(tmp_path)
    _save_run(conn, "qf-1", "2024-01-01T00:00:00Z", [
        _make_opp(title="Labor shortage", support_level="strong")
    ])
    result = get_trend_data(conn, "Vancouver", "Construction", limit_runs=5)
    assert len(result) >= 1
    for entry in result:
        assert "avg_confidence" in entry
        assert "trend_quality" in entry
        assert "padded_count" in entry
        assert "strong_count" in entry
        assert "weak_count" in entry
        assert "history_summary" in entry
        assert entry["trend_quality"] in ("investable", "monitor", "noise", "emerging", "declining")
    conn.close()


def test_trend_data_avg_confidence_populated(tmp_path: Path) -> None:
    conn = _tmp_conn(tmp_path)
    _save_run(conn, "conf-1", "2024-01-01T00:00:00Z", [
        _make_opp(title="Cost pressure", confidence=0.72, support_level="moderate")
    ])
    result = get_trend_data(conn, "Vancouver", "Construction", limit_runs=5)
    opp = next(r for r in result if "Cost" in r["title"])
    assert abs(opp["avg_confidence"] - 0.72) < 0.01
    conn.close()


# ── History summary grounding ─────────────────────────────────────────────────


def test_history_summary_investable_mentions_strong_count(tmp_path: Path) -> None:
    """Investable history_summary must mention the run count and strong appearances."""
    conn = _tmp_conn(tmp_path)
    for i, ts in enumerate(["2024-01-01T00:00:00Z", "2024-04-01T00:00:00Z", "2024-07-01T00:00:00Z"]):
        _save_run(conn, f"inv-{i}", ts, [
            _make_opp(title="Labor shortage", pain=7.5, confidence=0.8, support_level="strong")
        ])
    result = get_trend_data(conn, "Vancouver", "Construction", limit_runs=3)
    opp = next(r for r in result if "Labor" in r["title"])
    assert opp["trend_quality"] == "investable"
    summary = opp["history_summary"]
    assert "3" in summary
    assert "strong" in summary.lower()


def test_history_summary_noise_mentions_padded(tmp_path: Path) -> None:
    """Noise history_summary must mention padded appearances."""
    conn = _tmp_conn(tmp_path)
    for i, ts in enumerate(["2024-01-01T00:00:00Z", "2024-04-01T00:00:00Z"]):
        _save_run(conn, f"noise-{i}", ts, [
            _make_opp(title="Market dynamics", pain=3.0, confidence=0.25, support_level="weak", is_padded=True)
        ])
    result = get_trend_data(conn, "Vancouver", "Construction", limit_runs=5)
    opp = next(r for r in result if "Market" in r["title"])
    assert opp["trend_quality"] == "noise"
    assert "padded" in opp["history_summary"].lower() or "noise" in opp["history_summary"].lower()


def test_history_summary_emerging_mentions_new(tmp_path: Path) -> None:
    """Emerging history_summary should mention that this is a new signal."""
    conn = _tmp_conn(tmp_path)
    _save_run(conn, "em-1", "2024-06-01T00:00:00Z", [
        _make_opp(title="AI workflow", pain=8.0, confidence=0.85, support_level="strong")
    ])
    result = get_trend_data(conn, "Vancouver", "Construction", limit_runs=5)
    opp = next(r for r in result if "AI" in r["title"])
    assert opp["trend_quality"] == "emerging"
    assert "new" in opp["history_summary"].lower() or "cycle" in opp["history_summary"].lower()


# ── compare_runs: quality fields in aggregation ───────────────────────────────


def test_compare_runs_includes_padded_count(tmp_path: Path) -> None:
    """compare_runs aggregation must include padded_count per opportunity title."""
    conn = _tmp_conn(tmp_path)
    for i, ts in enumerate(["2024-01-01T00:00:00Z", "2024-06-01T00:00:00Z"]):
        padded = i == 0  # first run is padded, second is not
        _save_run(conn, f"cmp-padded-{i}", ts, [
            _make_opp(title="Market dynamics", pain=3.0, confidence=0.3, support_level="weak", is_padded=padded)
        ])
    _, opp_rows = compare_runs(conn, "Vancouver", "Construction", limit_runs=5)
    opp = next(r for r in opp_rows if "Market" in r["title"])
    assert "padded_count" in opp.keys()
    assert opp["padded_count"] == 1
    conn.close()


def test_compare_runs_includes_strong_count(tmp_path: Path) -> None:
    """compare_runs aggregation must include strong_count per opportunity title."""
    conn = _tmp_conn(tmp_path)
    for i, ts in enumerate(["2024-01-01T00:00:00Z", "2024-06-01T00:00:00Z"]):
        support = "strong" if i == 1 else "moderate"
        _save_run(conn, f"cmp-strong-{i}", ts, [
            _make_opp(title="Labor shortage", pain=7.5, confidence=0.75, support_level=support)
        ])
    _, opp_rows = compare_runs(conn, "Vancouver", "Construction", limit_runs=5)
    opp = next(r for r in opp_rows if "Labor" in r["title"])
    assert "strong_count" in opp.keys()
    assert opp["strong_count"] == 1
    conn.close()


def test_compare_runs_includes_weak_count(tmp_path: Path) -> None:
    conn = _tmp_conn(tmp_path)
    for i, ts in enumerate(["2024-01-01T00:00:00Z", "2024-06-01T00:00:00Z"]):
        support = "weak" if i == 0 else "moderate"
        _save_run(conn, f"cmp-weak-{i}", ts, [
            _make_opp(title="Supply chain", pain=4.5, confidence=0.4, support_level=support)
        ])
    _, opp_rows = compare_runs(conn, "Vancouver", "Construction", limit_runs=5)
    opp = next(r for r in opp_rows if "Supply" in r["title"])
    assert "weak_count" in opp.keys()
    assert opp["weak_count"] == 1
    conn.close()


def test_compare_runs_padded_all_zero_for_non_padded(tmp_path: Path) -> None:
    """When no opportunities are padded, padded_count must be 0."""
    conn = _tmp_conn(tmp_path)
    for i, ts in enumerate(["2024-01-01T00:00:00Z", "2024-06-01T00:00:00Z"]):
        _save_run(conn, f"cmp-nopad-{i}", ts, [
            _make_opp(title="Labor shortage", pain=7.5, confidence=0.75, support_level="strong", is_padded=False)
        ])
    _, opp_rows = compare_runs(conn, "Vancouver", "Construction", limit_runs=5)
    opp = next(r for r in opp_rows if "Labor" in r["title"])
    assert opp["padded_count"] == 0
    conn.close()


# ── Persistence of quality fields through save/load cycle ────────────────────


def test_quality_fields_persisted_to_db(tmp_path: Path) -> None:
    """support_level, is_padded, signal_age_days_avg, unique_sources_count are written to DB."""
    conn = _tmp_conn(tmp_path)
    _save_run(conn, "persist-1", "2024-06-01T00:00:00Z", [
        _make_opp(
            title="Labor shortage",
            support_level="strong",
            is_padded=False,
            signal_age_days_avg=8.5,
            unique_sources_count=4,
        )
    ])
    row = conn.execute(
        "SELECT support_level, is_padded, signal_age_days_avg, unique_sources_count "
        "FROM opportunities WHERE run_id='persist-1'"
    ).fetchone()
    assert row["support_level"] == "strong"
    assert row["is_padded"] == 0
    assert abs(row["signal_age_days_avg"] - 8.5) < 0.01
    assert row["unique_sources_count"] == 4
    conn.close()


def test_padded_opportunity_persisted_correctly(tmp_path: Path) -> None:
    conn = _tmp_conn(tmp_path)
    _save_run(conn, "pad-persist-1", "2024-06-01T00:00:00Z", [
        _make_opp(title="Market dynamics", support_level="weak", is_padded=True)
    ])
    row = conn.execute(
        "SELECT support_level, is_padded FROM opportunities WHERE run_id='pad-persist-1'"
    ).fetchone()
    assert row["support_level"] == "weak"
    assert row["is_padded"] == 1
    conn.close()


# ── Padded recurrence treated differently from real recurrence ────────────────


def test_padded_recurrence_does_not_become_investable(tmp_path: Path) -> None:
    """
    An opportunity appearing in every run as padded must NEVER be classified
    as investable, even with many appearances.
    """
    conn = _tmp_conn(tmp_path)
    for i, ts in enumerate([
        "2024-01-01T00:00:00Z",
        "2024-02-01T00:00:00Z",
        "2024-03-01T00:00:00Z",
        "2024-04-01T00:00:00Z",
        "2024-05-01T00:00:00Z",
    ]):
        _save_run(conn, f"padded-all-{i}", ts, [
            _make_opp(title="Market dynamics", pain=3.0, confidence=0.3, support_level="weak", is_padded=True)
        ])
    result = get_trend_data(conn, "Vancouver", "Construction", limit_runs=5)
    opp = next(r for r in result if "Market" in r["title"])
    assert opp["trend_quality"] != "investable", (
        f"Padded recurrence should never be investable, got: {opp['trend_quality']}"
    )
    assert opp["trend_quality"] == "noise"
    conn.close()


def test_real_recurrence_can_become_investable(tmp_path: Path) -> None:
    """
    An opportunity appearing in 3 runs with strong support and good confidence
    should be investable — proving the distinction from padded recurrence.
    """
    conn = _tmp_conn(tmp_path)
    for i, ts in enumerate([
        "2024-01-01T00:00:00Z",
        "2024-03-01T00:00:00Z",
        "2024-06-01T00:00:00Z",
    ]):
        _save_run(conn, f"real-strong-{i}", ts, [
            _make_opp(
                title="Labor shortage",
                pain=7.5,
                confidence=0.78,
                support_level="strong",
                is_padded=False,
            )
        ])
    result = get_trend_data(conn, "Vancouver", "Construction", limit_runs=5)
    opp = next(r for r in result if "Labor" in r["title"])
    assert opp["trend_quality"] == "investable"
    conn.close()
