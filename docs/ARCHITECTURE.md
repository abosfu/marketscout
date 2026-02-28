# MarketScout Architecture

This document explains the Scout → Brain → Strategist flow, CLI as primary interface, schema versioning, and caching. No UI; no sample data at runtime (fixtures only for tests).

## Overview

MarketScout is a **CLI-first Zero-Friction Strategy Engine**: you pass industry, objective, city, and location; the tool fetches live headlines and job signals, runs them through the Brain, and writes strategy.json, report.md, and report.html. Real signals only; sample data is used only in tests and the dev-only `demo` command.

## Components

### Scout

- **Role**: Ingest external signals (headlines, jobs) with no required API keys. **Live only at runtime**—no fallback to sample files.
- **Modules**: `scout/headlines.py` (Google News RSS, city/industry query; dedupe; retry with backoff; raises `ScoutError` on failure), `scout/jobs.py` (job-related RSS; retry; raises on failure).
- **Output**: Lists of normalized items. Combined they form the **signals** for the Brain.
- **Caching**: On success, data is written to `.cache/marketscout/` keyed by (city, industry, date). If a later fetch fails, valid (non-expired) cache is used and the user is warned.

### Brain

- **Role**: Turn signals + context (industry, objective, location) into a single, schema-validated strategy.
- **Modules**: `brain/schema.py`, `brain/strategy.py` (mock + optional LLM with fallback), `brain/report_md.py`, `brain/report_html.py`.
- **Output**: `StrategyOutput` (JSON) with pain score, signals_used, score_breakdown, problems, ai_matches, plan_30_60_90, roi_notes.

### Strategist

- The “strategist” is the same Brain layer. Strategy JSON is the single source of truth for report generation (MD, HTML) and any future integrations.

### Interface (CLI)

- **Primary command**: `marketscout run` — fetches live signals (or uses valid cache on fetch failure), generates strategy, writes strategy.json, report.md, report.html, and prints a Rich terminal summary (signals used, score breakdown, opportunity map, output paths).
- **Other commands**: `scout` (fetch and print/save JSON), `generate` (from file), `demo` (dev-only: build demo artifacts from data/sample_*).

## Schema versioning

- **`strategy_version`**: `"1.0"` or `"1.1"`. v1.1 adds `signals_used` and `score_breakdown`.
- Versioned output keeps report generators and future tools backward-compatible.

## Caching

- **Directory**: `.cache/marketscout/` (configurable via `MARKETSCOUT_CACHE_DIR`).
- **Key**: `cache_key(city, industry, date)` — one key per (city, industry, date).
- **Files**: `{key}.headlines.json`, `{key}.jobs.json`.
- **TTL**: `MARKETSCOUT_DISK_CACHE_TTL` seconds. Stale cache is not used when fetch fails; only valid (non-expired) cache is used as fallback with a warning.

## Data flow (summary)

```
CLI run (industry, objective, city, location)
    → Scout: fetch headlines + jobs (or use valid cache on failure)
    → Brain: generate StrategyOutput (mock or LLM)
    → Write strategy.json, report.md, report.html
    → Rich summary to terminal
```
