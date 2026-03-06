# MarketScout — Zero-Friction Strategy Engine (CLI)

> Given a **city** and an **industry**, fetch live signals and produce a ranked, evidence-backed Opportunity Map — in one command.

---

## What MarketScout is

MarketScout takes two inputs — a city and an industry — fetches live headlines (Google News RSS) and job postings (Adzuna or RSS), and writes a complete analysis pack to disk. No config files. No UI. Two flags in, seven files out.

**Outputs per run:**
- `strategy.json` — ranked opportunity map (5–8 items), each with pain score, ROI signal, confidence, and explainable `score_breakdown`
- `report.md` / `report.html` — full narrative report: Executive Summary, Signal Analysis, Opportunity Map
- `signal_analysis.json` — fetch metadata, keyword hits, data quality, per-source status (`live | cached | failed`)
- `leads.csv` — company-level leads: job count, top keywords, readiness score
- `eval_report.md` — quality-gate results written by `marketscout eval`

**Why trust the output:**
- Every `evidence.link` in `strategy.json` exists in `input_signals.json` — `eval` exits 1 if any link is absent
- `--deterministic` seeds random at 42 and sorts all signals — two runs on the same inputs produce bit-identical outputs
- `signal_analysis.json` records `live | cached | failed` per source; cache fallback is automatic and auditable
- 86 tests cover schema, evidence integrity, deterministic mode, fetch status, and CLI artifact creation

---

## Prerequisites

- **Python 3.11+** (`python3 --version`)
- **Adzuna API keys** — required for the default jobs provider. Register free at [developer.adzuna.com](https://developer.adzuna.com). You get `ADZUNA_APP_ID` and `ADZUNA_APP_KEY`.
- **No Adzuna keys?** Add `--jobs-provider rss` to any `run` command to pull jobs from RSS instead. This works without keys and is the easiest way to test locally.

---

## Installation

```bash
git clone https://github.com/your-username/marketscout.git
cd marketscout
python3 -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate

# Install dependencies
python3 -m pip install -r requirements.txt

# Optional but recommended: install the package so `marketscout` works as a command
python3 -m pip install -e .
```

**If you skip `pip install -e .`**, prefix every command with `PYTHONPATH=src`:

```bash
PYTHONPATH=src python3 -m marketscout run --city Vancouver --industry Construction
```

---

## API key setup

Register at [developer.adzuna.com](https://developer.adzuna.com) to get your `App ID` and `App Key`.

**Option 1 — temporary (current terminal session only):**

```bash
export ADZUNA_APP_ID=your_app_id_here
export ADZUNA_APP_KEY=your_app_key_here
export ADZUNA_COUNTRY=ca    # optional, defaults to ca
```

**Option 2 — persistent (create a local file, source it each session):**

```bash
# Create .env.local (already gitignored — do not commit this file)
cat > .env.local << 'EOF'
export ADZUNA_APP_ID=your_app_id_here
export ADZUNA_APP_KEY=your_app_key_here
export ADZUNA_COUNTRY=ca
EOF

source .env.local
```

> **Never commit API keys.** `.env.local` is listed in `.gitignore`. If you accidentally stage it, run `git reset HEAD .env.local`.

**Skip keys entirely:** pass `--jobs-provider rss` and the Adzuna provider is never called:

```bash
PYTHONPATH=src python3 -m marketscout run \
  --city Vancouver --industry Construction \
  --jobs-provider rss --deterministic
```

---

## Running the tool

```bash
# Vancouver — Construction
PYTHONPATH=src python3 -m marketscout run \
  --city Vancouver --industry Construction --deterministic

# Vancouver — Real Estate
PYTHONPATH=src python3 -m marketscout run \
  --city Vancouver --industry "Real Estate" --deterministic

# Toronto — Retail
PYTHONPATH=src python3 -m marketscout run \
  --city Toronto --industry Retail --deterministic
```

Each run writes artifacts to `out/<city>_<industry>_<date>/`.

---

## What each run produces

| File | Contents |
|------|----------|
| `input_signals.json` | Raw headlines and jobs as fetched — the ground truth for evidence links |
| `strategy.json` | v2.0 opportunity map: 5–8 items, each with `pain_score`, `roi_signal`, `confidence`, `score_breakdown`, `business_case`, and sourced `evidence` |
| `signal_analysis.json` | Fetch status per source, run metadata (timestamp, duration, `cache_used`), keyword hits, derived tags |
| `report.md` | Markdown report: Executive Summary, Signal Analysis, Opportunity Map with score breakdown |
| `report.html` | Same content as `report.md` in a self-contained HTML file |
| `summary.txt` | One-page text summary — data quality + top opportunities |
| `leads.csv` | Company-level leads: `company`, `job_count`, `top_keywords`, `readiness_score`, `example_links` |

> `out/` and `.cache/` are gitignored. Run `make clean` to remove both.

---

## Eval and bundle

**Find the latest run directory:**

```bash
RUN_DIR=$(ls -td out/*/ | head -n 1)
```

**Verify the run (quality gate):**

```bash
PYTHONPATH=src python3 -m marketscout eval \
  --signals "${RUN_DIR}input_signals.json" \
  --strategy "${RUN_DIR}strategy.json"
```

Writes `eval_report.md` next to `strategy.json`. Exit 0 if all checks pass, 1 otherwise. Checks include: schema validation, opportunity count, score bounds, evidence count, and — most importantly — that every `evidence.link` exists in `input_signals.json`.

**Pack into a shareable zip:**

```bash
PYTHONPATH=src python3 -m marketscout bundle \
  --out-dir "${RUN_DIR%/}"
```

Creates `bundle/` inside the run directory and writes `marketscout_<city>_<industry>_<date>.zip`. Prints the zip path on success.

---

## Troubleshooting

**`command not found: marketscout`**
The package is not installed. Either run `pip install -e .` or prefix commands with `PYTHONPATH=src python3 -m marketscout`.

**`No module named marketscout`**
Your virtual environment is not activated, or `PYTHONPATH` is not set. Run `source .venv/bin/activate` and retry, or use the `PYTHONPATH=src` prefix.

**`No module named pydantic`** (or `requests`, `rich`)
Dependencies are not installed. Run `python3 -m pip install -r requirements.txt`.

**Adzuna keys missing (`ScoutError: ADZUNA_APP_ID and ADZUNA_APP_KEY required`)**
Export the keys as shown in [API key setup](#api-key-setup), or add `--jobs-provider rss` to bypass Adzuna entirely.

**Jobs fetch fails even with valid keys**
Try `--allow-provider-fallback` to automatically fall back to the RSS provider if Adzuna returns an error.

**`NotOpenSSLWarning: urllib3 v2 only supports OpenSSL 1.1.1+`**
This is a macOS system Python warning about LibreSSL. It does **not** cause fetch failures — it can be ignored. Fetches still succeed.

**Run exits with code 1 and no `signal_analysis.json`**
Both live fetch and disk cache failed. Check your network connection and key configuration. Run with `--jobs-provider rss` to isolate whether the issue is Adzuna-specific.

---

## Testing

```bash
# Using make
make test

# Or directly
PYTHONPATH=src python3 -m pytest tests/ -v
```

86 tests covering: schema validation, deterministic mode, evidence link integrity, fetch status (live/cached/failed), CLI artifact creation, eval pass/fail cases, bundle creation, cache TTL, provider parsing, and input normalization. All tests run without network access — fetches are mocked.

---

## Demo scenarios

Three cities and industries chosen to show the engine working across different signal profiles — construction and real estate in a high-cost Canadian market, and retail in Canada's largest city.

**Vancouver — Construction**

![Vancouver Construction: Fetch Status, Data Quality, Top 5 Opportunities](assets/1.png)

**Vancouver — Real Estate**

![Vancouver Real Estate: Fetch Status, Data Quality, Top 5 Opportunities](assets/2.png)

**Toronto — Retail**

![Toronto Retail: Fetch Status, Data Quality, Top 5 Opportunities](assets/3.png)

---

## How to talk about this project

- **City + industry → opportunity map.** Two inputs, no config. The engine fetches live signals, maps them through industry keyword templates, and produces 5–8 ranked opportunities — each with a problem statement, sourced evidence, and estimated business case.
- **Live signals from news + jobs.** Headlines come from Google News RSS; job postings from Adzuna or RSS. Both sources are fetched fresh each run and cached to disk for resilience.
- **Proof metrics and score breakdown.** Every opportunity carries `score_breakdown: {signal_frequency, source_diversity, job_role_density}` summing to 1.0. These weights drive `pain_score` and `roi_signal` — the ranking is decomposable, not a black box.
- **Eval gate preventing hallucinated evidence.** `eval` cross-checks every `evidence.link` in `strategy.json` against `input_signals.json`. If any link is absent, the gate exits 1. You cannot ship an unverified report.
- **Deterministic mode for reproducibility.** `--deterministic` seeds random at 42, sorts all input signals by title, and uses stable opportunity ordering. Two runs on the same inputs produce bit-identical `strategy.json` — auditable and directly comparable.

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
| `--refresh` | off | Require fresh live fetch — exits 1 if network unavailable |
| `--deterministic` | off | Seed 42, stable signal + opportunity ordering |
| `--allow-provider-fallback` | off | Fall back to RSS if primary provider fails |
| `--no-write-leads` | off | Skip `leads.csv` export |

---

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ADZUNA_APP_ID` | — | Adzuna API App ID (required for Adzuna provider) |
| `ADZUNA_APP_KEY` | — | Adzuna API key (required for Adzuna provider) |
| `ADZUNA_COUNTRY` | `ca` | Adzuna country code |
| `MARKETSCOUT_CACHE_DIR` | `.cache/marketscout/` | Disk cache location |
| `MARKETSCOUT_DISK_CACHE_TTL` | `3600` | Cache TTL in seconds |
| `OPENAI_API_KEY` | — | Optional: enables LLM-based strategy generation |

---

## Architecture

- **Scout** — Fetches headlines (Google News RSS) and jobs (Adzuna or RSS). Falls back to disk cache on failure. Records `fetch_status` per source (`live | cached | failed`).
- **Brain** — Industry templates map keywords → bottleneck tags → opportunity titles. Scores `pain_score`, `automation_potential`, `roi_signal`, `confidence` from signal frequency, source diversity, and job role density. Produces `score_breakdown` weights summing to 1.0.
- **Reports** — Markdown and HTML generators consume `strategy.json` + `signal_analysis.json` and emit: Executive Summary, Fetch Status, Signal Analysis, Opportunity Map (with score breakdown), Leads summary, Sources.

Flow: `run` → fetch signals → build signal analysis → generate v2.0 strategy → write artifacts → print Rich tables.

---

## Repo layout

```
marketscout/
├── README.md
├── requirements.txt
├── pyproject.toml
├── Makefile
├── assets/
│   ├── 1.png                        # Vancouver Construction demo screenshot
│   ├── 2.png                        # Vancouver Real Estate demo screenshot
│   └── 3.png                        # Toronto Retail demo screenshot
├── src/marketscout/
│   ├── cli.py                       # run | eval | bundle — single entry point
│   ├── normalize.py                 # city + industry normalization and validation
│   ├── config.py                    # env-var overrides (cache TTL, strategy mode, etc.)
│   ├── cache.py                     # disk cache read/write with TTL
│   ├── fs.py                        # find_latest_run_dir (bundle default)
│   ├── leads.py                     # company-level lead scoring
│   ├── brain/
│   │   ├── schema.py                # v2.0 Pydantic models (StrategyOutput, ScoreBreakdown, …)
│   │   ├── strategy.py              # opportunity map generation, scoring, signal analysis
│   │   ├── report_md.py
│   │   └── report_html.py
│   ├── scout/                       # headlines (RSS) + jobs (Adzuna / RSS) fetchers
│   └── templates/                   # industry keyword maps → opportunity templates
└── tests/
    ├── fixtures/                    # sample data for tests only (never loaded at runtime)
    ├── conftest.py
    ├── test_cli.py                  # run, eval, bundle, fetch status, run metadata
    ├── test_strategy.py             # scoring, deterministic, evidence integrity, reports, leads
    ├── test_normalize.py            # city/industry normalization, template lookup, CLI validation
    ├── test_scout.py                # headlines, jobs, Adzuna provider
    └── test_cache.py                # cache key, TTL, read/write
```

---

## License

MIT. See [LICENSE](LICENSE).
