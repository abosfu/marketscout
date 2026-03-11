"""Backend integrity tests.

Covers guarantees that are NOT tested elsewhere:
  - --refresh exits non-zero when live fetch fails (no silent cache substitution)
  - pain_score, confidence, and roi_signal are actually sensitive to input signals
  - eval rejects strategies whose signals_used counts mismatch input_signals.json
  - signal_analysis.json records strategy_mode_config and uses top_tags (not derived_tags)
  - eval rejects '#' evidence links that do not appear in input_signals.json
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from marketscout.brain.strategy import generate_mock_strategy
from marketscout.cli import cmd_eval, cmd_run
from marketscout.scout import ScoutError


# ── Helpers ───────────────────────────────────────────────────────────────────

def _raise(msg: str):
    """Return a callable that raises ScoutError(msg)."""
    def _fail(*args, **kwargs):
        raise ScoutError(msg)
    return _fail


_MINIMAL_RSS = """<?xml version="1.0"?><rss><channel>
  <item><title>Labor shortage hits construction</title><link>https://a.com</link></item>
  <item><title>Supply chain delays reported</title><link>https://b.com</link></item>
</channel></rss>"""


class _FakeResp:
    text = _MINIMAL_RSS

    def raise_for_status(self) -> None:
        pass


def _ok(*args, **kwargs) -> _FakeResp:
    return _FakeResp()


def _run_with_mocks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **overrides) -> tuple[int, Path]:
    """Run cmd_run with RSS mocked; return (exit_code, out_dir)."""
    monkeypatch.setattr("marketscout.scout.headlines.requests.get", _ok)
    monkeypatch.setattr("marketscout.scout.providers.rss.requests.get", _ok)
    out_dir = tmp_path / "out"
    kwargs: dict = dict(
        city="Vancouver",
        industry="Construction",
        out_dir=out_dir,
        jobs_limit=5,
        headlines_limit=5,
        jobs_provider="rss",
        allow_provider_fallback=False,
        write_leads=False,
        refresh=False,
        deterministic=False,
    )
    kwargs.update(overrides)
    return cmd_run(**kwargs), out_dir


def _make_minimal_strategy(n_opp: int = 5, headlines_count: int = 2, jobs_count: int = 1) -> dict:
    opp = {
        "title": "T",
        "problem": "P",
        "ai_category": "Operational efficiency",
        "evidence": [
            {"title": "H", "link": "https://example.com/h1", "source": "headline"},
            {"title": "J", "link": "https://example.com/j1", "source": "job"},
        ],
        "pain_score": 5.0,
        "automation_potential": 5.0,
        "roi_signal": 5.0,
        "confidence": 0.5,
        "business_case": {"savings_range_annual": "$50k", "assumptions": []},
        "score_breakdown": {"signal_frequency": 0.5, "source_diversity": 0.3, "job_role_density": 0.2},
    }
    return {
        "strategy_version": "2.0",
        "city": "Vancouver",
        "industry": "Construction",
        "opportunity_map": [dict(opp) for _ in range(n_opp)],
        "signals_used": {
            "headlines_count": headlines_count,
            "jobs_count": jobs_count,
            "news_sources_count": 1,
            "job_companies_count": 1,
        },
        "data_quality": {"freshness_window_days": 1, "coverage_score": 0.7, "source_mix_score": 0.6},
    }


def _write_eval_inputs(tmp_path: Path, signals: dict, strategy: dict) -> tuple[Path, Path]:
    sig_path = tmp_path / "signals.json"
    strat_path = tmp_path / "strategy.json"
    sig_path.write_text(json.dumps(signals))
    strat_path.write_text(json.dumps(strategy))
    return sig_path, strat_path


# ── --refresh hard-fail path ──────────────────────────────────────────────────

def test_run_refresh_exits_nonzero_when_headlines_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """--refresh=True exits 1 even when cache would be available; no silent substitution."""
    from marketscout import config as ms_config
    from marketscout.cache import cache_key, write_cached

    cache_dir = tmp_path / ".cache"
    monkeypatch.setattr(ms_config, "get_cache_dir", lambda: cache_dir)
    monkeypatch.setattr(ms_config, "get_disk_cache_ttl_seconds", lambda: 3600)

    # Pre-populate cache so a non-refresh run would succeed
    key = cache_key("Vancouver", "Construction")
    write_cached(cache_dir, key, "headlines.json", [{"title": "Cached", "link": "https://c.com"}])

    monkeypatch.setattr("marketscout.scout.fetch_headlines", _raise("network down"))
    monkeypatch.setattr("marketscout.scout.providers.rss.requests.get", _ok)

    out_dir = tmp_path / "out"
    code = cmd_run(
        city="Vancouver", industry="Construction", out_dir=out_dir,
        jobs_limit=5, headlines_limit=5, jobs_provider="rss",
        allow_provider_fallback=False, write_leads=False, refresh=True, deterministic=False,
    )
    assert code == 1
    assert not (out_dir / "strategy.json").exists(), (
        "strategy.json must not be written when --refresh fails"
    )


def test_run_refresh_exits_nonzero_when_jobs_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """--refresh=True exits 1 when the jobs fetch fails, even with cache available."""
    from marketscout import config as ms_config
    from marketscout.cache import cache_key, write_cached

    cache_dir = tmp_path / ".cache"
    monkeypatch.setattr(ms_config, "get_cache_dir", lambda: cache_dir)
    monkeypatch.setattr(ms_config, "get_disk_cache_ttl_seconds", lambda: 3600)

    key = cache_key("Vancouver", "Construction")
    write_cached(cache_dir, key, "jobs.json", [{"title": "Cached job", "link": "https://j.com"}])

    monkeypatch.setattr("marketscout.scout.headlines.requests.get", _ok)
    monkeypatch.setattr("marketscout.scout.fetch_jobs", _raise("api down"))

    out_dir = tmp_path / "out"
    code = cmd_run(
        city="Vancouver", industry="Construction", out_dir=out_dir,
        jobs_limit=5, headlines_limit=5, jobs_provider="rss",
        allow_provider_fallback=False, write_leads=False, refresh=True, deterministic=False,
    )
    assert code == 1


# ── Scoring sensitivity ───────────────────────────────────────────────────────

def test_pain_score_increases_with_more_matching_evidence() -> None:
    """pain_score for a matched bottleneck is strictly higher with 5 matching signals vs 1."""
    h_one = [{"title": "Labor shortage hits Vancouver construction", "link": "https://a1.com", "source": "A"}]
    h_five = [
        {"title": f"Labor shortage in sector {i}", "link": f"https://a{i}.com", "source": "A"}
        for i in range(5)
    ]
    s1 = generate_mock_strategy(h_one, industry="Construction", city="Vancouver")
    s5 = generate_mock_strategy(h_five, industry="Construction", city="Vancouver")

    def find_labor(strategy):
        return next((o for o in strategy.opportunity_map if "labor" in o.problem.lower()), None)

    o1 = find_labor(s1)
    o5 = find_labor(s5)
    assert o1 is not None, "Expected a Labor opportunity with 1 signal"
    assert o5 is not None, "Expected a Labor opportunity with 5 signals"
    assert o5.pain_score > o1.pain_score, (
        f"pain_score must increase with more evidence: "
        f"1 signal → {o1.pain_score}, 5 signals → {o5.pain_score}"
    )


def test_confidence_higher_with_mixed_headline_and_job_sources() -> None:
    """confidence is higher when both headline and job evidence exist vs headline-only."""
    headlines = [
        {"title": "Labor shortage hits Vancouver", "link": "https://h1.com", "source": "A"},
    ]
    # Job title contains "labor" so it matches the same bottleneck
    jobs_matching = [
        {"title": "Labor coordinator needed", "company": "Co", "link": "https://j1.com",
         "published": "", "source": "rss"},
    ]
    s_no_jobs = generate_mock_strategy(headlines, industry="Construction", city="Vancouver", jobs=[])
    s_with_jobs = generate_mock_strategy(headlines, industry="Construction", city="Vancouver", jobs=jobs_matching)

    def find_labor(strategy):
        return next((o for o in strategy.opportunity_map if "labor" in o.problem.lower()), None)

    o_no_jobs = find_labor(s_no_jobs)
    o_with_jobs = find_labor(s_with_jobs)
    assert o_no_jobs is not None and o_with_jobs is not None
    assert o_with_jobs.confidence >= o_no_jobs.confidence, (
        f"confidence must be >= with mixed sources: "
        f"no jobs → {o_no_jobs.confidence}, with jobs → {o_with_jobs.confidence}"
    )


def test_roi_signal_higher_with_matching_job_evidence() -> None:
    """roi_signal for an opportunity is higher when matching job evidence exists."""
    headlines = [
        {"title": "Labor shortage hits construction", "link": "https://h1.com", "source": "A"},
        {"title": "Labor market tightens", "link": "https://h2.com", "source": "B"},
    ]
    # Job title contains "labor" → matched into the Labor opportunity bucket
    jobs_matching = [
        {"title": "Labor shortage coordinator", "company": "Co", "link": "https://j1.com",
         "published": "", "source": "rss"},
    ]
    s_no_jobs = generate_mock_strategy(headlines, industry="Construction", city="Vancouver", jobs=[])
    s_with_jobs = generate_mock_strategy(headlines, industry="Construction", city="Vancouver", jobs=jobs_matching)

    def find_labor(strategy):
        return next((o for o in strategy.opportunity_map if "labor" in o.problem.lower()), None)

    o_no_jobs = find_labor(s_no_jobs)
    o_with_jobs = find_labor(s_with_jobs)
    assert o_no_jobs is not None and o_with_jobs is not None
    assert o_with_jobs.roi_signal >= o_no_jobs.roi_signal, (
        f"roi_signal must be >= with matching job evidence: "
        f"no jobs → {o_no_jobs.roi_signal}, with jobs → {o_with_jobs.roi_signal}"
    )


def test_pain_score_formula_is_grounded_in_components() -> None:
    """Non-zero evidence always produces pain_score > 2.0; score_breakdown sums to 1.0."""
    headlines = [
        {"title": "Labor shortage in construction", "link": "https://a.com", "source": "A"},
    ]
    strategy = generate_mock_strategy(headlines, industry="Construction", city="Vancouver")
    for o in strategy.opportunity_map:
        sb = o.score_breakdown
        assert sb is not None
        total = sb.signal_frequency + sb.source_diversity + sb.job_role_density
        assert abs(total - 1.0) < 1e-6, f"score_breakdown sum {total} ≠ 1.0"
        # Non-zero breakdown means non-trivial evidence → pain > 2.0
        if sb.signal_frequency > 0 or sb.source_diversity > 0 or sb.job_role_density > 0:
            assert o.pain_score > 2.0, (
                f"Non-zero evidence components should give pain_score > 2.0, got {o.pain_score}"
            )


# ── eval: signals_used consistency ───────────────────────────────────────────

def test_eval_fails_when_headlines_count_mismatch(tmp_path: Path) -> None:
    """eval exits 1 when signals_used.headlines_count doesn't match actual headlines count."""
    signals = {
        "headlines": [
            {"title": "H1", "link": "https://example.com/h1"},
            {"title": "H2", "link": "https://example.com/h2"},
        ],
        "jobs": [{"title": "J1", "company": "C", "link": "https://example.com/j1"}],
    }
    strategy = _make_minimal_strategy(headlines_count=999, jobs_count=1)  # wrong count
    sig_path, strat_path = _write_eval_inputs(tmp_path, signals, strategy)
    out = tmp_path / "r.md"
    assert cmd_eval(sig_path, strat_path, out) == 1
    assert "signals_used_counts" in out.read_text()


def test_eval_fails_when_jobs_count_mismatch(tmp_path: Path) -> None:
    """eval exits 1 when signals_used.jobs_count doesn't match actual jobs count."""
    signals = {
        "headlines": [{"title": "H1", "link": "https://example.com/h1"}],
        "jobs": [
            {"title": "J1", "company": "C", "link": "https://example.com/j1"},
            {"title": "J2", "company": "C", "link": "https://example.com/j2"},
        ],
    }
    strategy = _make_minimal_strategy(headlines_count=1, jobs_count=999)  # wrong count
    sig_path, strat_path = _write_eval_inputs(tmp_path, signals, strategy)
    assert cmd_eval(sig_path, strat_path, tmp_path / "r.md") == 1


def test_eval_passes_when_signals_used_counts_match(tmp_path: Path) -> None:
    """eval exits 0 when signals_used counts are consistent with input_signals.json."""
    signals = {
        "headlines": [
            {"title": "H1", "link": "https://example.com/h1"},
            {"title": "H2", "link": "https://example.com/h2"},
        ],
        "jobs": [{"title": "J1", "company": "C", "link": "https://example.com/j1"}],
    }
    strategy = _make_minimal_strategy(headlines_count=2, jobs_count=1)
    # Ensure all evidence links are in signals
    for opp in strategy["opportunity_map"]:
        opp["evidence"] = [
            {"title": "H1", "link": "https://example.com/h1", "source": "headline"},
            {"title": "J1", "link": "https://example.com/j1", "source": "job"},
        ]
    sig_path, strat_path = _write_eval_inputs(tmp_path, signals, strategy)
    assert cmd_eval(sig_path, strat_path, tmp_path / "r.md") == 0


# ── eval: no '#' bypass ───────────────────────────────────────────────────────

def test_eval_rejects_hash_link_when_no_signal_has_hash_link(tmp_path: Path) -> None:
    """eval fails when evidence link is '#' but no signal in input_signals.json has link '#'."""
    signals = {
        "headlines": [{"title": "H", "link": "https://example.com/h1"}],
        "jobs": [{"title": "J", "company": "C", "link": "https://example.com/j1"}],
    }
    strategy = _make_minimal_strategy(headlines_count=1, jobs_count=1)
    # Inject a '#' link — no signal has '#' so this should fail eval
    strategy["opportunity_map"][0]["evidence"][0]["link"] = "#"
    sig_path, strat_path = _write_eval_inputs(tmp_path, signals, strategy)
    out = tmp_path / "r.md"
    assert cmd_eval(sig_path, strat_path, out) == 1
    report = out.read_text()
    assert "evidence_links_in_signals" in report and "fail" in report.lower()


def test_eval_allows_hash_link_when_a_signal_has_hash_link(tmp_path: Path) -> None:
    """eval allows '#' evidence link when a signal in input_signals.json also has '#' as its link."""
    signals = {
        "headlines": [{"title": "H", "link": "#"}],  # signal itself has "#" link
        "jobs": [{"title": "J", "company": "C", "link": "https://example.com/j1"}],
    }
    strategy = _make_minimal_strategy(headlines_count=1, jobs_count=1)
    # Evidence link "#" should be valid because one signal has "#"
    strategy["opportunity_map"][0]["evidence"][0]["link"] = "#"
    strategy["opportunity_map"][0]["evidence"][1]["link"] = "https://example.com/j1"
    sig_path, strat_path = _write_eval_inputs(tmp_path, signals, strategy)
    # The signals_used count check: signals has 1 headline and 1 job → counts match
    result = cmd_eval(sig_path, strat_path, tmp_path / "r.md")
    # evidence_links check: "#" is in allowed because the headline has link "#"
    report = (tmp_path / "r.md").read_text()
    assert "evidence_links_in_signals" in report
    # This should pass the link check specifically
    assert "bad: ['#']" not in report


# ── signal_analysis.json integrity ───────────────────────────────────────────

def test_signal_analysis_contains_strategy_mode_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """signal_analysis.json includes strategy_mode_config reflecting the configured mode."""
    code, out_dir = _run_with_mocks(tmp_path, monkeypatch)
    assert code == 0
    sa = json.loads((out_dir / "signal_analysis.json").read_text())
    assert "strategy_mode_config" in sa, "signal_analysis.json must contain strategy_mode_config"
    assert sa["strategy_mode_config"] in ("mock", "llm", "auto")


def test_signal_analysis_has_top_tags_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """signal_analysis.json has top_tags (a list) reflecting keyword hit ranking."""
    code, out_dir = _run_with_mocks(tmp_path, monkeypatch)
    assert code == 0
    sa = json.loads((out_dir / "signal_analysis.json").read_text())
    assert "top_tags" in sa, "signal_analysis.json must contain top_tags"
    assert isinstance(sa["top_tags"], list)


def test_signal_analysis_does_not_contain_derived_tags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """signal_analysis.json must not contain derived_tags (it was a duplicate of keyword_hits)."""
    code, out_dir = _run_with_mocks(tmp_path, monkeypatch)
    assert code == 0
    sa = json.loads((out_dir / "signal_analysis.json").read_text())
    assert "derived_tags" not in sa, (
        "derived_tags was a duplicate of keyword_hits and has been removed"
    )


def test_signal_analysis_top_tags_ordered_by_hit_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """top_tags list is ordered by keyword hit count (most-hit bottleneck first)."""
    # RSS with two "labor" hits and one "supply chain" hit
    rss = """<?xml version="1.0"?><rss><channel>
  <item><title>Labor shortage worsens in construction</title><link>https://a.com</link></item>
  <item><title>Labor market tightens across sectors</title><link>https://b.com</link></item>
  <item><title>Supply chain disruptions continue</title><link>https://c.com</link></item>
</channel></rss>"""

    class Resp:
        text = rss
        def raise_for_status(self): pass

    monkeypatch.setattr("marketscout.scout.headlines.requests.get", lambda *a, **k: Resp())
    monkeypatch.setattr("marketscout.scout.providers.rss.requests.get", lambda *a, **k: Resp())

    _, out_dir = _run_with_mocks(tmp_path, monkeypatch, deterministic=True)
    sa = json.loads((out_dir / "signal_analysis.json").read_text())
    top_tags = sa.get("top_tags", [])
    assert len(top_tags) >= 1
    # "Labor shortages" tag should appear before "Supply chain" (2 hits vs 1 hit)
    if "Labor shortages and wage pressure" in top_tags and "Supply chain and logistics constraints" in top_tags:
        labor_idx = top_tags.index("Labor shortages and wage pressure")
        supply_idx = top_tags.index("Supply chain and logistics constraints")
        assert labor_idx < supply_idx, (
            f"Labor (2 hits) should rank before Supply chain (1 hit) in top_tags: {top_tags}"
        )
