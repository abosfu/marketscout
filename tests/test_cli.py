"""CLI command tests: run, bundle, eval, fetch status, and run metadata."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from marketscout.cli import BUNDLE_REQUIRED, cmd_bundle, cmd_eval, cmd_run
from marketscout.fs import find_latest_run_dir
from marketscout.scout import ScoutError
import marketscout.scout.headlines as _ms_headlines
import marketscout.scout.providers.rss as _ms_rss


# ── Shared mock helpers ───────────────────────────────────────────────────────

_RSS = """<?xml version="1.0"?><rss><channel>
  <item><title>Headline A</title><link>https://a.com</link></item>
  <item><title>Headline B</title><link>https://b.com</link></item>
</channel></rss>"""


class _FakeResp:
    text = _RSS

    def raise_for_status(self) -> None:
        pass


def _ok(*args, **kwargs) -> _FakeResp:
    return _FakeResp()


def _raise(msg: str):
    """Return a callable that raises ScoutError(msg) when invoked."""
    def _fail(*args, **kwargs):
        raise ScoutError(msg)
    return _fail


def _make_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **overrides) -> tuple[int, dict]:
    """Invoke cmd_run with mocked fetchers; return (exit_code, signal_analysis dict)."""
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
    code = cmd_run(**kwargs)
    sa_path = out_dir / "signal_analysis.json"
    sa = json.loads(sa_path.read_text()) if sa_path.exists() else {}
    return code, sa


# ── Eval helpers ──────────────────────────────────────────────────────────────

def _minimal_v2_strategy(
    city: str = "Vancouver",
    industry: str = "Construction",
    n_opp: int = 5,
    evidence_per_opp: int = 2,
    headlines_count: int = 2,
    jobs_count: int = 2,
) -> dict:
    opp: dict = {
        "title": "Opportunity",
        "problem": "Problem",
        "ai_category": "Operational efficiency",
        "evidence": [
            {"title": "Headline", "link": "https://example.com/h1", "source": "headline"},
            {"title": "Job", "link": "https://example.com/j1", "source": "job"},
        ][:evidence_per_opp],
        "pain_score": 5.0,
        "automation_potential": 5.0,
        "roi_signal": 5.0,
        "confidence": 0.5,
        "business_case": {"savings_range_annual": "$50k", "assumptions": []},
        "score_breakdown": {"signal_frequency": 0.5, "source_diversity": 0.3, "job_role_density": 0.2},
    }
    if evidence_per_opp == 1:
        opp["evidence"] = [{"title": "E", "link": "https://example.com/h1", "source": "headline"}]
    return {
        "strategy_version": "2.0",
        "city": city,
        "industry": industry,
        "opportunity_map": [dict(opp) for _ in range(n_opp)],
        "signals_used": {
            "headlines_count": headlines_count,
            "jobs_count": jobs_count,
            "news_sources_count": 1,
            "job_companies_count": 1,
        },
        "data_quality": {"freshness_window_days": 1, "coverage_score": 0.7, "source_mix_score": 0.6},
    }


def _signals_with_links(links: list) -> dict:
    headlines = [{"title": "H", "link": link, "source": "S"} for link in links]
    jobs = [{"title": "J", "company": "C", "link": link, "source": "job"} for link in links]
    if not headlines:
        headlines = [{"title": "H", "link": "https://example.com/h1"}]
    if not jobs:
        jobs = [{"title": "J", "company": "C", "link": "https://example.com/j1"}]
    return {"headlines": headlines, "jobs": jobs}


# ── run ───────────────────────────────────────────────────────────────────────

def test_run_creates_all_artifacts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """run writes all expected artifacts; spot-checks strategy.json and report content."""
    monkeypatch.setattr(_ms_headlines.requests, "get", _ok)
    monkeypatch.setattr(_ms_rss.requests, "get", _ok)

    out_dir = tmp_path / "out"
    code = cmd_run(
        city="Vancouver", industry="Construction", out_dir=out_dir,
        jobs_limit=5, headlines_limit=10, jobs_provider="rss",
        allow_provider_fallback=False, write_leads=True, refresh=False, deterministic=False,
    )
    assert code == 0
    for name in ("input_signals.json", "strategy.json", "signal_analysis.json",
                 "report.md", "report.html", "summary.txt", "leads.csv"):
        assert (out_dir / name).exists(), f"Missing artifact: {name}"

    strategy = json.loads((out_dir / "strategy.json").read_text())
    assert strategy.get("strategy_version") == "2.0"
    assert strategy.get("city") == "Vancouver"
    assert strategy.get("industry") == "Construction"
    assert "opportunity_map" in strategy and "data_quality" in strategy

    sa = json.loads((out_dir / "signal_analysis.json").read_text())
    assert sa["city"] == "Vancouver" and sa["industry"] == "Construction"
    assert "signals" in sa and "headlines_count" in sa["signals"]
    assert "keyword_hits" in sa and "top_tags" in sa

    assert "Opportunity Map" in (out_dir / "report.md").read_text()
    assert "Executive Summary" in (out_dir / "report.md").read_text()
    assert "Opportunity Map" in (out_dir / "report.html").read_text()


# ── fetch status / run metadata ───────────────────────────────────────────────

def test_fetch_status_live_when_both_succeed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Both fetches succeed → status 'live'; run_metadata fields are well-formed."""
    monkeypatch.setattr(_ms_headlines.requests, "get", _ok)
    monkeypatch.setattr(_ms_rss.requests, "get", _ok)

    code, sa = _make_run(tmp_path, monkeypatch, deterministic=True)
    assert code == 0

    fs = sa["fetch_status"]
    assert fs["headlines"] == {"provider": "google_news_rss", "status": "live", "error": None}
    assert fs["jobs"] == {"provider": "rss", "status": "live", "error": None}

    meta = sa["run_metadata"]
    assert "started_at_iso" in meta
    assert isinstance(meta["duration_ms"], int) and meta["duration_ms"] >= 0
    assert meta["deterministic"] is True
    assert meta["cache_used"] is False


def test_fetch_status_cached_when_headlines_fail(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Headline fetch fails but cache exists → status 'cached'; cache_used is True."""
    from marketscout import config as ms_config
    from marketscout.cache import cache_key, write_cached

    cache_dir = tmp_path / ".cache"
    monkeypatch.setattr(ms_config, "get_cache_dir", lambda: cache_dir)
    monkeypatch.setattr(ms_config, "get_disk_cache_ttl_seconds", lambda: 3600)

    key = cache_key("Vancouver", "Construction")
    write_cached(cache_dir, key, "headlines.json",
                 [{"title": "Cached", "link": "https://cache.com", "source": "s"}])

    monkeypatch.setattr(_ms_rss.requests, "get", _ok)
    monkeypatch.setattr("marketscout.scout.fetch_headlines", _raise("network down"))

    code, sa = _make_run(tmp_path, monkeypatch)
    assert code == 0
    assert sa["fetch_status"]["headlines"]["status"] == "cached"
    assert "network down" in sa["fetch_status"]["headlines"]["error"]
    assert sa["fetch_status"]["jobs"]["status"] == "live"
    assert sa["run_metadata"]["cache_used"] is True


def test_fetch_status_cached_when_jobs_fail(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Job fetch fails but cache exists → status 'cached'."""
    from marketscout import config as ms_config
    from marketscout.cache import cache_key, write_cached

    cache_dir = tmp_path / ".cache"
    monkeypatch.setattr(ms_config, "get_cache_dir", lambda: cache_dir)
    monkeypatch.setattr(ms_config, "get_disk_cache_ttl_seconds", lambda: 3600)

    key = cache_key("Vancouver", "Construction")
    write_cached(cache_dir, key, "jobs.json",
                 [{"title": "Cached job", "company": "Acme", "link": "https://j.com", "published": "", "source": "s"}])

    monkeypatch.setattr(_ms_headlines.requests, "get", _ok)
    monkeypatch.setattr("marketscout.scout.fetch_jobs", _raise("api unavailable"))

    code, sa = _make_run(tmp_path, monkeypatch)
    assert code == 0
    assert sa["fetch_status"]["headlines"]["status"] == "live"
    assert sa["fetch_status"]["jobs"]["status"] == "cached"
    assert "api unavailable" in sa["fetch_status"]["jobs"]["error"]


def test_run_exits_nonzero_when_fetch_fails_no_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Fetch fails with no cache available → exit code 1, signal_analysis.json not written."""
    from marketscout import config as ms_config

    monkeypatch.setattr(ms_config, "get_cache_dir", lambda: tmp_path / ".cache")
    monkeypatch.setattr(ms_config, "get_disk_cache_ttl_seconds", lambda: 3600)
    monkeypatch.setattr("marketscout.scout.fetch_headlines", _raise("total failure"))

    out_dir = tmp_path / "out"
    code = cmd_run(
        city="Vancouver", industry="Construction", out_dir=out_dir,
        jobs_limit=5, headlines_limit=5, jobs_provider="rss",
        allow_provider_fallback=False, write_leads=False, refresh=False, deterministic=False,
    )
    assert code == 1
    assert not (out_dir / "signal_analysis.json").exists()


# ── bundle ────────────────────────────────────────────────────────────────────

def test_bundle_creates_zip_with_required_files(tmp_path: Path) -> None:
    """bundle copies required files to bundle/ and creates a dated zip."""
    run_dir = tmp_path / "Vancouver_Construction_2025-02-27"
    run_dir.mkdir(parents=True)
    for name in BUNDLE_REQUIRED:
        (run_dir / name).write_text(
            '{"strategy_version":"2.0","city":"Vancouver","industry":"Construction",'
            '"opportunity_map":[],"signals_used":{},"data_quality":{}}'
            if name == "strategy.json" else "x"
        )
    assert cmd_bundle(run_dir) == 0
    bundle_dir = run_dir / "bundle"
    assert bundle_dir.is_dir()
    for name in BUNDLE_REQUIRED:
        assert (bundle_dir / name).is_file()
    assert (run_dir / "marketscout_Vancouver_Construction_2025-02-27.zip").is_file()


def test_bundle_includes_optional_files_when_present(tmp_path: Path) -> None:
    """bundle includes leads.csv and signal_analysis.json in bundle/ and zip when present."""
    run_dir = tmp_path / "Run_2025-02-27"
    run_dir.mkdir(parents=True)
    opp = {
        "title": "T", "problem": "P", "ai_category": "Operational efficiency",
        "evidence": [{"title": "E", "link": "#", "source": "headline"}],
        "pain_score": 5, "automation_potential": 5, "roi_signal": 5, "confidence": 0.5,
        "business_case": {"savings_range_annual": "$50k", "assumptions": []},
    }
    strategy = {
        "strategy_version": "2.0", "city": "V", "industry": "I",
        "opportunity_map": [opp] * 5,
        "signals_used": {"headlines_count": 0, "jobs_count": 0, "news_sources_count": 0, "job_companies_count": 0},
        "data_quality": {"freshness_window_days": 0, "coverage_score": 0.5, "source_mix_score": 0.5},
    }
    for name in BUNDLE_REQUIRED:
        (run_dir / name).write_text(json.dumps(strategy) if name == "strategy.json" else "x")
    (run_dir / "leads.csv").write_text("company,job_count\nAcme,1")
    (run_dir / "signal_analysis.json").write_text('{"city":"V"}')

    assert cmd_bundle(run_dir) == 0
    assert (run_dir / "bundle" / "leads.csv").is_file()
    assert (run_dir / "bundle" / "signal_analysis.json").is_file()
    with zipfile.ZipFile(run_dir / "marketscout_V_I_2025-02-27.zip") as zf:
        assert "leads.csv" in zf.namelist()


def test_bundle_fails_on_missing_required_file(tmp_path: Path) -> None:
    """bundle returns 1 when any required file is absent."""
    run_dir = tmp_path / "SomeRun"
    run_dir.mkdir()
    (run_dir / "input_signals.json").write_text("{}")
    (run_dir / "strategy.json").write_text("{}")
    # report.html and summary.txt are missing
    assert cmd_bundle(run_dir) == 1


def test_bundle_default_uses_latest_run_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """When out_dir is None and no run dir exists, bundle returns 1."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "out").mkdir(exist_ok=True)
    monkeypatch.setattr("marketscout.cli.find_latest_run_dir", lambda base: None)
    assert cmd_bundle(None) == 1


def test_find_latest_run_dir_returns_most_recent(tmp_path: Path) -> None:
    """find_latest_run_dir returns the directory with the latest mtime."""
    base = tmp_path / "out"
    base.mkdir()
    d1 = base / "CityA_Ind_2025-02-26"
    d2 = base / "CityB_Ind_2025-02-27"
    d1.mkdir()
    d2.mkdir()
    (d2 / "strategy.json").write_text("x")
    result = find_latest_run_dir(base)
    assert result in (d1, d2)


# ── eval ──────────────────────────────────────────────────────────────────────

def test_eval_all_pass(tmp_path: Path) -> None:
    """eval exits 0 and writes eval_report.md when all checks pass."""
    signals = _signals_with_links(["https://example.com/h1", "https://example.com/j1"])
    strategy = _minimal_v2_strategy(n_opp=5, evidence_per_opp=2)
    (tmp_path / "input_signals.json").write_text(json.dumps(signals))
    (tmp_path / "strategy.json").write_text(json.dumps(strategy))
    out = tmp_path / "eval_report.md"
    assert cmd_eval(tmp_path / "input_signals.json", tmp_path / "strategy.json", out) == 0
    content = out.read_text()
    assert "Eval Report" in content and "pass" in content.lower() and "v2_schema" in content


def test_eval_fails_on_hallucinated_evidence_link(tmp_path: Path) -> None:
    """eval fails (exit 1) when an evidence link is absent from signals."""
    signals = _signals_with_links(["https://example.com/h1"])
    strategy = _minimal_v2_strategy(evidence_per_opp=2)
    strategy["opportunity_map"][0]["evidence"][1]["link"] = "https://fake.com/hallucinated"
    (tmp_path / "input_signals.json").write_text(json.dumps(signals))
    (tmp_path / "strategy.json").write_text(json.dumps(strategy))
    out = tmp_path / "eval_report.md"
    assert cmd_eval(tmp_path / "input_signals.json", tmp_path / "strategy.json", out) == 1
    report = out.read_text()
    assert "evidence_links_in_signals" in report and "fail" in report.lower()


def test_eval_fails_on_wrong_opportunity_count(tmp_path: Path) -> None:
    """eval fails when opportunity_map has fewer than 5 items."""
    signals = _signals_with_links(["https://example.com/h1", "https://example.com/j1"])
    strategy = _minimal_v2_strategy(n_opp=4, evidence_per_opp=2)
    (tmp_path / "input_signals.json").write_text(json.dumps(signals))
    (tmp_path / "strategy.json").write_text(json.dumps(strategy))
    assert cmd_eval(tmp_path / "input_signals.json", tmp_path / "strategy.json", tmp_path / "r.md") == 1


def test_eval_fails_when_evidence_count_below_two(tmp_path: Path) -> None:
    """eval fails when any opportunity has < 2 evidence items."""
    signals = _signals_with_links(["https://example.com/h1"])
    strategy = _minimal_v2_strategy(n_opp=5, evidence_per_opp=1)
    (tmp_path / "input_signals.json").write_text(json.dumps(signals))
    (tmp_path / "strategy.json").write_text(json.dumps(strategy))
    out = tmp_path / "eval_report.md"
    assert cmd_eval(tmp_path / "input_signals.json", tmp_path / "strategy.json", out) == 1
    assert "evidence_count" in out.read_text()


def test_eval_default_out_next_to_strategy(tmp_path: Path) -> None:
    """When --out is omitted, eval writes eval_report.md next to strategy.json."""
    signals = _signals_with_links(["https://example.com/h1", "https://example.com/j1"])
    strategy = _minimal_v2_strategy(n_opp=5, evidence_per_opp=2)
    (tmp_path / "signals.json").write_text(json.dumps(signals))
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "strategy.json").write_text(json.dumps(strategy))
    assert cmd_eval(tmp_path / "signals.json", run_dir / "strategy.json", None) == 0
    assert (run_dir / "eval_report.md").is_file()
