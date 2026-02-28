# MarketScout — Zero-Friction Strategy Engine (CLI)

MarketScout is a **CLI tool** that fetches live business headlines and job signals, runs them through a strategy engine (mock or optional LLM), and writes **strategy.json**, **report.md**, and **report.html**. You pass industry, objective, city, and location; no API keys required for the Scout. Real signals only at runtime—sample data is used only in tests and fixtures.

---

## Quickstart

```bash
cd marketscout
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Run with live signals (network required)
python -m marketscout run --industry Construction --objective "Market entry" --city Vancouver --location "Vancouver, BC"
```

Outputs are written to `out/` by default: `strategy.json`, `report.md`, `report.html`. The terminal shows a summary (signals used, score breakdown, opportunity map).

---

## Example command (Vancouver + Construction)

```bash
PYTHONPATH=src python -m marketscout run \
  --industry Construction \
  --objective "Market entry" \
  --city Vancouver \
  --location "Vancouver, BC" \
  -o out
```

Or with Make (from repo root):

```bash
make run
```

---

## Output artifacts

| File | Description |
|------|-------------|
| `strategy.json` | Full schema-validated strategy (pain_score, signals_used, score_breakdown, problems, ai_matches, plan_30_60_90, roi_notes) |
| `report.md` | Human-readable Markdown report (Executive Summary, Signals Used, Score Breakdown, Opportunity Map, AI Matches, 30/60/90 Plan, ROI, Sources) |
| `report.html` | Same sections as Markdown in a minimal HTML report |

---

## Architecture

- **Scout**: Fetches headlines (Google News RSS) and jobs (job-related RSS). No API keys. Retries with backoff; raises a clear error on failure. No sample fallback at runtime.
- **Brain**: Generates strategy from signals + (industry, objective, location). Mock (keyword-based, industry templates) or LLM (OpenAI) when `OPENAI_API_KEY` is set; fallback to mock on LLM failure.
- **Strategist**: Same Brain layer; strategy JSON is the single source of truth for reports.

Flow: `run` → fetch headlines + jobs → (optional: use cache if fetch fails but cache valid) → generate strategy → write strategy.json, report.md, report.html → print Rich summary.

---

## Caching

- **Directory**: `.cache/marketscout/` (override with `MARKETSCOUT_CACHE_DIR`).
- **Key**: `(city, industry, date)` so each day and query has its own cache file.
- **TTL**: Configurable via `MARKETSCOUT_DISK_CACHE_TTL` (seconds; default 3600). If a live fetch fails but valid (non-expired) cached data exists, the CLI uses it and prints a warning.
- Cached data is previously fetched real data, not sample/fake data.

---

## Modes and env vars

| Variable | Description |
|----------|-------------|
| `MARKETSCOUT_MODE` | `mock` (default) \| `llm` \| `auto`. In `auto`, Brain tries OpenAI if `OPENAI_API_KEY` is set; otherwise mock. |
| `OPENAI_API_KEY` | Optional. When set and mode is `auto`, strategy can be generated via OpenAI with fallback to mock. |
| `MARKETSCOUT_DEFAULT_CITY` | Default city for RSS (e.g. Vancouver). |
| `MARKETSCOUT_MAX_HEADLINES` | Max headlines to fetch (default 10). |
| `MARKETSCOUT_DISK_CACHE_TTL` | Disk cache TTL in seconds (default 3600). |
| `MARKETSCOUT_CACHE_DIR` | Override cache directory (default: `.cache/marketscout`). |

---

## CLI commands

| Command | Description |
|---------|-------------|
| `run` | **Primary.** Fetch live headlines + jobs, generate strategy, write strategy.json + report.md + report.html, print Rich summary. |
| `scout` | Fetch live headlines (and optionally jobs); print or save JSON. Exits non-zero on fetch failure. |
| `generate` | Load headlines (+ jobs) from a JSON file and write strategy.json. For offline use with pre-fetched data. |
| `demo` | **[Dev-only]** Build demo_input.json and demo_strategy.json from `data/sample_*` (no network). For tests/fixtures. |

---

## Tests

```bash
pip install -r requirements.txt
make test
# or
PYTHONPATH=src pytest tests/ -v
```

Tests do not rely on sample fallback at runtime. Fetch is mocked where needed. Fixtures and `data/sample_*.json` are used only in tests and the dev-only `demo` command.

---

## Repo layout

```
marketscout/
├── README.md
├── CHANGELOG.md
├── requirements.txt
├── pyproject.toml
├── Makefile
├── data/                    # Sample data for tests/fixtures only
│   ├── sample_headlines.json
│   ├── sample_jobs.json
│   └── sample_strategy.json
├── src/marketscout/
│   ├── __init__.py
│   ├── cli.py               # run | scout | generate | demo
│   ├── config.py
│   ├── cache.py             # Disk cache (key, TTL, read/write)
│   ├── scout/
│   │   ├── headlines.py     # Live RSS; retry; raise on failure
│   │   └── jobs.py          # Live RSS; retry; raise on failure
│   ├── brain/
│   │   ├── schema.py
│   │   ├── strategy.py
│   │   ├── report_md.py
│   │   └── report_html.py
│   └── templates/
│       └── industries.py
├── docs/
│   ├── ARCHITECTURE.md
│   ├── DEMO_SCRIPT.md
│   └── RELEASE_CHECKLIST.md
└── tests/
    ├── test_cache.py
    ├── test_cli_run.py
    ├── test_headlines.py
    ├── test_jobs.py
    ├── test_strategy.py
    ├── test_schema.py
    ├── test_report_md.py
    ├── test_report_html.py
    └── test_demo.py
```

---

## License

MIT. See [LICENSE](LICENSE).
