# MarketScout — Zero-Friction Strategy Engine (CLI)

> Given a **city** and an **industry**, fetch live signals and produce a ranked, evidence-backed Opportunity Map — in one command.

---

## What it does

MarketScout pulls real headlines (Google News RSS) and job listings (Adzuna or RSS), runs them through a deterministic strategy engine, and writes a complete analysis pack to disk. Every claim in the output is traceable to a source in `input_signals.json`. A built-in quality gate (`eval`) verifies that — no hallucinated links allowed.

**No sample data at runtime.** All fixture files live in `tests/fixtures/` and are never loaded by the CLI. If a live fetch fails, the CLI falls back to the disk cache (`.cache/marketscout/`) and records the fallback in `signal_analysis.json`.

---

## 1-minute demo

```bash
# 1. Generate the opportunity map
python -m marketscout run --city Vancouver --industry Construction --deterministic

# 2. Verify quality (schema, evidence links, no hallucination)
python -m marketscout eval \
  --signals out/vancouver_construction_<date>/input_signals.json \
  --strategy out/vancouver_construction_<date>/strategy.json

# 3. Pack everything into a shareable zip
python -m marketscout bundle --out-dir out/vancouver_construction_<date>
```

![Terminal output showing Fetch Status, Data Quality and Top 5 Opportunities tables](assets/terminal.png)
*Replace with an actual screenshot: `python -m marketscout run --city Vancouver --industry Construction`*

![report.html open in browser — Executive Summary and Opportunity Map](assets/report.png)
*Replace with an actual screenshot of `out/.../report.html` in a browser*

![eval_report.md — all checks passing](assets/eval.png)
*Replace with an actual screenshot of `marketscout eval` output*

---

## Quickstart

```bash
cd marketscout
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

python -m marketscout run --city Vancouver --industry Construction
```

Outputs land in `out/<city>_<industry>_<date>/`.

> **Generated paths — never committed:**
> | Path | Contents |
> |------|----------|
> | `out/` | All run artifacts (`strategy.json`, `report.html`, `leads.csv`, …). Gitignored. |
> | `.cache/` | Disk cache of live-fetched signals with configurable TTL. Gitignored. |
>
> Run `make clean` to remove both.

---

## Artifacts

| File | Description |
|------|-------------|
| `input_signals.json` | Raw headlines + jobs fetched as input |
| `strategy.json` | v2.0: city, industry, opportunity_map (5–8 items + score_breakdown), signals_used, data_quality |
| `signal_analysis.json` | Fetch status, run metadata, keyword_hits, derived_tags |
| `report.md` | Full Markdown report: Executive Summary, Signal Analysis, Opportunity Map, score breakdown, sources |
| `report.html` | Same structure as Markdown in a minimal HTML report |
| `summary.txt` | Terminal-friendly summary (data quality + top opportunities) |
| `leads.csv` | Company-level leads: company, job_count, top_keywords, readiness_score |
| `eval_report.md` | Quality-gate results (written by `eval`) |

![leads.csv open in a spreadsheet view](assets/leads.png)
*Replace with an actual screenshot of `out/.../leads.csv`*

---

## Screenshot checklist

Capture these before publishing or sharing:

- [ ] `assets/terminal.png` — `python -m marketscout run --city Vancouver --industry Construction`: Fetch Status + Data Quality + Top 5 Opportunities.
- [ ] `assets/report.png` — open `out/.../report.html` in a browser: Executive Summary + Signal Analysis + Opportunity Map.
- [ ] `assets/eval.png` — `python -m marketscout eval ...` output or `eval_report.md` showing all checks passing.
- [ ] `assets/leads.png` — `out/.../leads.csv` top rows in a spreadsheet or editor.

---

## Eval: trust gate

```bash
python -m marketscout eval \
  --signals out/vancouver_construction_<date>/input_signals.json \
  --strategy out/vancouver_construction_<date>/strategy.json
```

Writes `eval_report.md` next to the strategy file. Exit code **0** if all pass, **1** otherwise.

Checks:

- Strategy validates v2.0 schema
- `opportunity_map` length in [5, 8]
- Each opportunity: confidence in [0, 1], scores in [0, 10]
- Each opportunity has ≥ 2 evidence items
- Every `evidence.link` is present in `input_signals.json` (no hallucinated sources)
- `data_quality.coverage_score` in [0, 1]
- Each `score_breakdown` (when present) sums to 1.0

---

## Bundle: share a run

```bash
# Auto-discovers latest run under out/
python -m marketscout bundle

# Specific run directory
python -m marketscout bundle --out-dir out/vancouver_construction_<date>
```

Validates required files, copies artifacts into `bundle/`, and writes `marketscout_<city>_<industry>_<date>.zip` inside the run directory. Prints the zip path.

---

## Interview talking points

**Why CLI?**
Minimal surface area. No server, no database, no UI framework to maintain. The interface is three commands; everything else is a file. Easy to test, easy to automate, easy to demonstrate in a terminal recording.

**Why the eval gate? (no hallucinated links)**
LLM outputs and even heuristic engines can reference sources that were never in the input. `eval` cross-checks every `evidence.link` against `input_signals.json` before accepting a run. Exit code 1 fails CI — you can't accidentally ship an unverified report.

**Why deterministic mode?**
Reproducibility is a trust signal. `--deterministic` seeds `random` at 42, sorts input signals by title before processing, and uses stable opportunity ordering. Two runs on the same inputs produce bit-identical `strategy.json` — auditable and comparable.

**Why score_breakdown?**
Each opportunity carries `{signal_frequency, source_diversity, job_role_density}` that sum to 1.0. These weights drive the final `pain_score` rather than being decorative — the score is explainable and the `eval` gate verifies the constraint. Interviewers can ask "why is this ranked first?" and get a decomposable answer.

**Caching resilience**
If a live fetch fails, the CLI falls back to the disk cache (`.cache/marketscout/`, configurable TTL). `signal_analysis.json` records `fetch_status` per source (`live | cached | failed`) and `run_metadata` (timestamp, duration, `cache_used`), so every run is fully auditable even under degraded network conditions.

---

## CLI reference

| Command | Description |
|---------|-------------|
| `run` | **Primary.** Fetch signals, generate v2.0 strategy, write all artifacts. |
| `eval` | Quality gate: validate v2.0 strategy and evidence links; write eval_report.md. |
| `bundle` | Copy artifacts into `bundle/` and create a zip; default is latest run under `out/`. |

### `run` options

| Flag | Default | Description |
|------|---------|-------------|
| `--city` | *(required)* | City to research |
| `--industry` | *(required)* | Industry to research |
| `--out-dir` / `-o` | `out/<city>_<industry>_<date>/` | Output directory |
| `--jobs-provider` | `adzuna` | Jobs provider: `adzuna` or `rss` |
| `--jobs-limit` | `10` | Max jobs to fetch |
| `--headlines-limit` | `10` | Max headlines to fetch |
| `--refresh` | off | Force re-fetch (ignore cache) |
| `--deterministic` | off | Seed 42, stable signal and opportunity ordering |
| `--allow-provider-fallback` | off | Fall back to RSS if primary provider fails |
| `--no-write-leads` | off | Skip leads.csv export |

---

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MARKETSCOUT_CACHE_DIR` | `.cache/marketscout/` | Disk cache location |
| `MARKETSCOUT_DISK_CACHE_TTL` | `3600` | Cache TTL in seconds |
| `ADZUNA_APP_ID` | — | Adzuna API App ID |
| `ADZUNA_API_KEY` | — | Adzuna API key |
| `OPENAI_API_KEY` | — | Optional: enables LLM-based strategy generation |

---

## Architecture

- **Scout** — Fetches headlines (Google News RSS) and jobs (Adzuna or RSS). Retries with backoff; falls back to disk cache on failure. Records fetch status per source.
- **Brain** — Industry templates map keywords → bottleneck tags → opportunity titles. Scores `pain_score`, `automation_potential`, `roi_signal`, `confidence` from signal frequency, source diversity, and job role density. Produces `score_breakdown` weights that sum to 1.0.
- **Reports** — Markdown and HTML generators consume `strategy.json` + `signal_analysis.json` and emit: Executive Summary, Fetch Status, Signal Analysis, Opportunity Map (with score breakdown), Leads summary, Sources.

Flow: `run` → fetch signals (record status) → build signal analysis → generate v2.0 strategy → write artifacts → print Rich tables.

---

## Tests

```bash
pip install -e ".[dev]"
make test
# or
PYTHONPATH=src pytest tests/ -v
```

86 tests covering schema validation, deterministic mode, evidence link integrity, fetch status (live/cached/failed), CLI artifact creation, eval pass/fail cases, bundle creation, cache TTL, and provider parsing.

---

## Repo layout

```
marketscout/
├── README.md
├── pyproject.toml
├── Makefile
├── assets/                      # screenshot placeholders (replace with real screenshots)
│   ├── terminal.png
│   ├── report.png
│   ├── eval.png
│   └── leads.png
├── src/marketscout/
│   ├── cli.py                   # run | eval | bundle — single entry point
│   ├── normalize.py             # city + industry normalization and validation
│   ├── config.py                # env-var overrides (cache TTL, strategy mode, etc.)
│   ├── cache.py                 # disk cache read/write with TTL
│   ├── fs.py                    # find_latest_run_dir (bundle default)
│   ├── leads.py                 # company-level lead scoring
│   ├── brain/
│   │   ├── schema.py            # v2.0 Pydantic models (StrategyOutput, ScoreBreakdown, …)
│   │   ├── strategy.py          # opportunity map generation, scoring, signal analysis
│   │   ├── report_md.py
│   │   └── report_html.py
│   ├── scout/                   # headlines (RSS) + jobs (Adzuna / RSS) fetchers
│   └── templates/               # industry keyword maps → opportunity templates
└── tests/
    ├── fixtures/                # sample data for tests only (never loaded at runtime)
    │   ├── sample_headlines.json
    │   ├── sample_jobs.json
    │   ├── sample_strategy_v2.json
    │   └── sample_rss.xml
    ├── conftest.py
    ├── test_cli.py              # run, eval, bundle, fetch status, run metadata
    ├── test_strategy.py         # scoring, deterministic, evidence integrity, reports, leads
    ├── test_normalize.py        # city/industry normalization, template lookup, CLI validation
    ├── test_scout.py            # headlines, jobs, Adzuna provider
    └── test_cache.py            # cache key, TTL, read/write
```

---

## License

MIT. See [LICENSE](LICENSE).
