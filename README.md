# MarketScout — Zero-Friction Strategy Engine (CLI)

> Given a **city** and an **industry**, fetch live signals and produce a ranked, evidence-backed Opportunity Map — in one command.

---

## What it does

MarketScout takes two inputs — a city and an industry — and writes a complete analysis pack to disk. It fetches live headlines (Google News RSS) and job postings (Adzuna or RSS), maps them through industry keyword templates, and produces a scored, sourced opportunity map with no configuration beyond those two flags.

**Outputs:**

- `strategy.json` — ranked opportunity map (5–8 items), each with pain score, ROI signal, confidence, and explainable `score_breakdown`
- `report.md` / `report.html` — full narrative report: Executive Summary, Signal Analysis, Opportunity Map
- `signal_analysis.json` — fetch metadata, keyword hits, data quality, per-source status (`live | cached | failed`)
- `leads.csv` — company-level leads with job count, top keywords, and readiness score
- `eval_report.md` — quality-gate results written by `marketscout eval`

**Why trust it:**

- Every `evidence.link` in the output exists in `input_signals.json` — `eval` exits 1 if any link is absent (no hallucinated sources)
- `--deterministic` seeds random at 42 and sorts all signals by title — two runs on the same data produce bit-identical outputs
- Cache fallback is automatic and transparent: `signal_analysis.json` records `live | cached | failed` per source
- 86 tests cover schema validation, evidence integrity, deterministic mode, fetch status, and CLI artifact creation

---

## 1-minute demo

```bash
# 1. Generate the opportunity map
marketscout run --city Vancouver --industry Construction --deterministic

# 2. Verify quality (schema, evidence links, no hallucination)
marketscout eval \
  --signals out/vancouver_construction_<date>/input_signals.json \
  --strategy out/vancouver_construction_<date>/strategy.json

# 3. Pack everything into a shareable zip
marketscout bundle --out-dir out/vancouver_construction_<date>
```

![Terminal output — Fetch Status, Data Quality, Top 5 Opportunities](assets/terminal.png)

![report.html — Executive Summary and Opportunity Map](assets/report.png)

![eval_report.md — all checks passing](assets/eval.png)

---

## Quickstart

```bash
cd marketscout
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

marketscout run --city Vancouver --industry Construction
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
| `report.html` | Same structure as Markdown in a self-contained HTML file |
| `summary.txt` | Terminal-friendly summary (data quality + top opportunities) |
| `leads.csv` | Company-level leads: company, job_count, top_keywords, readiness_score |
| `eval_report.md` | Quality-gate results (written by `eval`) |

![leads.csv in a spreadsheet view](assets/leads.png)

---

## Screenshot checklist

Capture these before publishing or sharing:

- [ ] `assets/terminal.png` — `marketscout run --city Vancouver --industry Construction`: Fetch Status + Data Quality + Top 5 Opportunities
- [ ] `assets/report.png` — open `out/.../report.html` in a browser: Executive Summary + Signal Analysis + Opportunity Map
- [ ] `assets/eval.png` — `marketscout eval ...` output or `eval_report.md` showing all checks passing
- [ ] `assets/leads.png` *(optional)* — `out/.../leads.csv` top rows in a spreadsheet or editor

---

## Interview talking points

**Two inputs → opportunity map**
Just `--city` and `--industry`. No config files, no templates to fill in. The engine maps fetched signals through industry keyword templates to produce 5–8 ranked opportunities — each with problem statement, evidence, and estimated business case.

**Proof metrics + score_breakdown**
Every opportunity carries `score_breakdown: {signal_frequency, source_diversity, job_role_density}` summing to 1.0. These weights drive the final `pain_score` and `roi_signal` — the ranking is decomposable, not a black box. The `eval` gate verifies the sum constraint.

**Deterministic mode**
`--deterministic` seeds `random` at 42, sorts all input signals by title before processing, and uses stable opportunity ordering. Two runs on the same inputs produce bit-identical `strategy.json` — auditable and directly comparable.

**Eval gate: no hallucinated sources**
Every `evidence.link` in `strategy.json` must exist in `input_signals.json`. `eval` cross-checks this and exits 1 if any link is absent. You cannot ship an unverified report — the gate is machine-enforced and CI-friendly.

**Cache fallback resilience**
If a live fetch fails, the CLI falls back to the disk cache (`.cache/marketscout/`, configurable TTL). `signal_analysis.json` records `fetch_status` per source (`live | cached | failed`) and `run_metadata` (timestamp, duration, `cache_used`), so every run is auditable even under degraded network conditions.

---

## CLI reference

| Command | Description |
|---------|-------------|
| `run` | **Primary.** Fetch signals, generate v2.0 strategy, write all artifacts. |
| `eval` | Quality gate: validate schema, evidence links, and scores; write `eval_report.md`. Exit 0 if all pass, 1 otherwise. |
| `bundle` | Validate artifacts, copy to `bundle/`, create zip. Defaults to latest run under `out/`. |

### `run` options

| Flag | Default | Description |
|------|---------|-------------|
| `--city` | *(required)* | City to research |
| `--industry` | *(required)* | Industry to research |
| `--out-dir` / `-o` | `out/<city>_<industry>_<date>/` | Output directory |
| `--jobs-provider` | `adzuna` | Jobs provider: `adzuna` or `rss` |
| `--jobs-limit` | `10` | Max jobs to fetch |
| `--headlines-limit` | `10` | Max headlines to fetch |
| `--refresh` | off | Require fresh live fetch — exits 1 if network is unavailable |
| `--deterministic` | off | Seed 42, stable signal + opportunity ordering |
| `--allow-provider-fallback` | off | Fall back to RSS if primary provider fails |
| `--no-write-leads` | off | Skip `leads.csv` export |

---

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MARKETSCOUT_CACHE_DIR` | `.cache/marketscout/` | Disk cache location |
| `MARKETSCOUT_DISK_CACHE_TTL` | `3600` | Cache TTL in seconds |
| `ADZUNA_APP_ID` | — | Adzuna API App ID |
| `ADZUNA_APP_KEY` | — | Adzuna API key |
| `OPENAI_API_KEY` | — | Optional: enables LLM-based strategy generation |

---

## Architecture

- **Scout** — Fetches headlines (Google News RSS) and jobs (Adzuna or RSS). Falls back to disk cache on failure. Records `fetch_status` per source.
- **Brain** — Industry templates map keywords → bottleneck tags → opportunity titles. Scores `pain_score`, `automation_potential`, `roi_signal`, `confidence` from signal frequency, source diversity, and job role density. Produces `score_breakdown` weights summing to 1.0.
- **Reports** — Markdown and HTML generators consume `strategy.json` + `signal_analysis.json` and emit: Executive Summary, Fetch Status, Signal Analysis, Opportunity Map (with score breakdown), Leads summary, Sources.

Flow: `run` → fetch signals → build signal analysis → generate v2.0 strategy → write artifacts → print Rich tables.

---

## Tests

```bash
pip install -e ".[dev]"
make test
# or
PYTHONPATH=src pytest tests/ -v
```

86 tests covering schema validation, deterministic mode, evidence link integrity, fetch status (live/cached/failed), CLI artifact creation, eval pass/fail, bundle creation, cache TTL, and provider parsing.

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
