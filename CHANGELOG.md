# Changelog

All notable changes to MarketScout are documented here.

## [1.1.0] — 2025-02-27

### Added

- **CLI `run` command**: Primary interface. Fetches live headlines + jobs (no sample fallback at runtime), generates strategy, writes `strategy.json`, `report.md`, `report.html` to an output directory, prints Rich terminal summary (signals used, score breakdown, opportunity map).
- **Disk cache**: `.cache/marketscout/` keyed by (city, industry, date). TTL configurable via `MARKETSCOUT_DISK_CACHE_TTL`. If live fetch fails but valid cache exists, use cache and warn.
- **Rich dependency**: Used for aesthetic terminal output (tables, header, output paths).
- **Cache module**: `cache.py` with `cache_key`, `is_cache_valid`, `read_cached`, `write_cached` (pure functions + TTL behavior covered by tests).
- **Tests**: `test_cache.py` (keying, TTL, read/write), `test_cli_run.py` (run creates output files with mocked fetch).

### Changed

- **Scout**: No sample fallback at runtime. `fetch_headlines` and `fetch_jobs` raise `ScoutError` on failure; retry with backoff. Sample data used only in tests and `demo` command.
- **CLI**: `run` is primary; `scout` / `generate` retained; `demo` marked dev-only (fixtures/tests).
- **README**: Rewritten for CLI tool (quickstart, example command, output artifacts, architecture, caching, modes, commands). Streamlit Cloud section removed.
- **docs/ARCHITECTURE.md**: CLI-first, no UI, caching, no sample at runtime.
- **docs/DEMO_SCRIPT.md**: CLI demo script (pitch, walkthrough, talking points).
- **Makefile**: `make run` runs `marketscout run` with default args.
- **pyproject.toml**: version 1.1.0; Streamlit removed; Rich added.

### Removed

- **Streamlit**: Removed from dependencies. Deleted `app.py` and `streamlit_app.py`. Product is CLI-only.
- **Sample fallback in Scout**: Runtime no longer falls back to `data/sample_*.json`; only tests and `demo` use sample data.

---

## [1.0.0] — 2025-02-27

### Added

- **Demo Mode**: Streamlit checkbox “Demo Mode (guaranteed output)” uses only `data/sample_headlines.json` and `data/sample_jobs.json`; no network calls. Guarantees a working run offline or in restricted environments.
- **Live Mode**: Default mode still fetches headlines and jobs with graceful fallback to sample data on failure.
- **CLI `demo` command**: `python -m marketscout demo` writes `./data/demo_input.json` (combined sample headlines + jobs) and `./data/demo_strategy.json` (generated strategy) without using the network.
- **HTML report export**: `brain/report_html.py` converts `StrategyOutput` to a clean HTML report (same sections as Markdown). Download button in Streamlit for `strategy_report.html`. Minimal inline styling.
- **Streamlit Cloud support**: Repo-root entrypoint `app.py` imports and runs the Streamlit app; `.streamlit/config.toml` added with basic server/browser settings.
- **Documentation**: `docs/ARCHITECTURE.md` (Scout/Brain/Strategist/UI, schema versioning, 3-click UX); `docs/DEMO_SCRIPT.md` (45-second pitch, 2-minute walkthrough, talking points); `docs/RELEASE_CHECKLIST.md` (GitHub release checklist).
- **README**: Live Demo placeholder, “How to deploy to Streamlit Cloud”, Demo Mode instructions, “Resume bullets” section.

### Changed

- **Streamlit**: Replaced “Use sample data” toggle with “Demo Mode (guaranteed output)” checkbox. Download Report section now includes JSON, Markdown, and HTML.
- **Makefile**: `make run` uses `streamlit run app.py` with `PYTHONPATH=src`.

### Fixed

- N/A

---

Format based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
