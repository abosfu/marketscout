# MarketScout

A local market intelligence tool that takes a city and industry as input, runs a live signal pipeline, and returns a scored opportunity map you can query in plain English.

## What It Does

- **Input**: a city and an industry (e.g. Vancouver, Construction)
- **Pipeline**: fetches live headlines and job postings, scores opportunities using pain/ROI signals, persists results to a SQLite Gold layer
- **Output**: a ranked opportunity table in the Streamlit dashboard, an NL2SQL chat interface for ad-hoc queries, and an email briefing on demand

## Stack

| Component | Technology |
|-----------|-----------|
| Pipeline | Python, Google News RSS, Adzuna Jobs API |
| Database | SQLite, SQLAlchemy 2.0 (Medallion star schema) |
| Backend | FastAPI, Pydantic v2, uvicorn |
| AI / NL2SQL | LangChain, Google Gemini (`gemini-1.5-pro-latest`) |
| Frontend | Streamlit |
| Email | smtplib, Gmail SMTP / STARTTLS |

## Quick Start

1. **Clone and enter the repo**
   ```bash
   git clone https://github.com/your-username/marketscout.git
   cd marketscout
   ```

2. **Create and activate a virtual environment**
   ```bash
   python -m venv .venv && source .venv/bin/activate
   ```

3. **Install the package**
   ```bash
   pip install -e .
   ```

4. **Configure environment variables**
   ```bash
   cp .env.example .env
   # Open .env and fill in ADZUNA_APP_ID, ADZUNA_APP_KEY, GOOGLE_API_KEY at minimum
   ```

5. **Start the backend and frontend** (two terminals)
   ```bash
   # Terminal 1
   make backend
   # or: uvicorn marketscout.backend.main:app --reload --port 8000

   # Terminal 2
   make frontend
   # or: streamlit run src/marketscout/frontend/app.py
   ```

6. **Open the app**
   ```
   http://localhost:8501
   ```

## Environment Variables

| Variable | Required | Purpose |
|----------|----------|---------|
| `ADZUNA_APP_ID` | Yes | Adzuna Jobs API app ID |
| `ADZUNA_APP_KEY` | Yes | Adzuna Jobs API key |
| `ADZUNA_COUNTRY` | No | ISO country code for Adzuna (default: `ca`) |
| `GOOGLE_API_KEY` | Yes | Gemini API key for NL2SQL chat |
| `OPENAI_API_KEY` | No | OpenAI key for LLM strategy generation; omit to use rule-based scoring |
| `SMTP_USER` | No | Gmail address for email briefings |
| `SMTP_APP_PASSWORD` | No | Gmail app password for email briefings |
| `BRIEFING_RECIPIENT` | No | Address to deliver email briefings |
| `MARKETSCOUT_MODE` | No | Strategy mode: `auto` (default), `mock`, or `llm` |
| `MARKETSCOUT_DEFAULT_CITY` | No | Default city when none is supplied (default: `Vancouver`) |
| `MARKETSCOUT_MAX_HEADLINES` | No | Max headlines fetched per run (default: `10`) |
| `MARKETSCOUT_DISK_CACHE_TTL` | No | Disk cache TTL in seconds (default: `3600`) |
| `MARKETSCOUT_CACHE_DIR` | No | Cache directory path (default: `.cache/marketscout/`) |
| `MARKETSCOUT_DB_PATH` | No | SQLite database path (default: `.cache/marketscout/marketscout.db`) |

## Running Tests

```bash
pytest tests/ -q
```

115 tests, 1 skipped. All tests run without network access or live API keys — every HTTP and LLM call is monkeypatched.

## Architecture

The pipeline is organised in three discrete layers following the Medallion Architecture pattern. The Bronze layer is raw signal ingestion: `scout/headlines.py` fetches Google News RSS headlines for the given city and industry, and `scout/jobs.py` queries the Adzuna Jobs API for relevant postings. Results are disk-cached with a configurable TTL so repeated runs within the cache window do not make network calls. Each signal carries its source, title, URL, and a captured-at timestamp.

The Silver layer is scoring and normalisation. `backend/ai/strategy.py` receives the raw headline and job lists, deduplicates by content hash, maps keyword hits to bottleneck categories, and computes an `OpportunityItem` for each detected opportunity with `pain_score`, `roi_signal`, `confidence`, and a `score_breakdown` dict. When `OPENAI_API_KEY` is set and `MARKETSCOUT_MODE` is `auto` or `llm`, GPT-4o-mini is used for scoring; otherwise the pipeline falls back to deterministic rule-based scoring. The output is a `StrategyOutput` object that can be serialised to JSON.

The Gold layer is persistence. After scoring, `db.py` opens a SQLAlchemy session and writes to four tables: `dim_runs` (one row per pipeline execution), `dim_opportunities` (one row per scored opportunity), `dim_signals` (deduplicated headline and job rows), and `fact_leads` (the join between opportunities and their supporting signals with scores). The write path is idempotent — re-running with the same `run_id` does not insert duplicate rows. Once written, the Gold layer is exposed read-only to the NL2SQL layer: the SQLite connection is opened with `?mode=ro` URI mode and a keyword guard rejects any generated SQL containing `DROP`, `DELETE`, `UPDATE`, or `INSERT` before execution.

## Project Structure

```
marketscout/
├── .env.example                     # copy to .env and fill in keys
├── Makefile                         # make backend | make frontend | make test
├── pyproject.toml                   # package config and dependencies
├── src/marketscout/
│   ├── __init__.py
│   ├── cli.py                       # marketscout CLI (run, eval, bundle)
│   ├── config.py                    # dotenv loader, env-var helpers
│   ├── db.py                        # Gold layer: SQLAlchemy ORM, write_gold(), init_db()
│   ├── normalize.py                 # city and industry normalisation
│   ├── cache.py                     # disk cache with TTL
│   ├── leads.py                     # company-level lead extraction
│   ├── fs.py                        # filesystem helpers
│   ├── backend/
│   │   ├── main.py                  # FastAPI app: POST /search, /ask, /email
│   │   ├── nl2sql.py                # LangChain NL2SQL pipeline + read-only guard
│   │   ├── schema.py                # Pydantic v2 models
│   │   ├── email_sender.py          # Gmail SMTP briefing sender
│   │   └── ai/
│   │       ├── strategy.py          # opportunity scoring (rule-based + LLM)
│   │       ├── report_html.py       # HTML report renderer
│   │       └── report_md.py         # Markdown report renderer
│   ├── scout/
│   │   ├── headlines.py             # Google News RSS fetcher (Bronze)
│   │   ├── jobs.py                  # jobs dispatcher
│   │   └── providers/
│   │       ├── adzuna.py            # Adzuna Jobs API provider
│   │       ├── rss.py               # RSS jobs fallback provider
│   │       └── base.py              # provider base class
│   ├── frontend/
│   │   └── app.py                   # Streamlit dashboard (search, KPIs, NL2SQL chat, email)
│   └── templates/
│       └── industries.py            # keyword maps and opportunity templates
└── tests/
    ├── test_backend.py              # FastAPI endpoint tests (httpx + ASGITransport)
    ├── test_db.py                   # Gold layer ORM tests
    ├── test_api.py                  # NL2SQL safety gate tests
    ├── test_strategy.py             # scoring and schema tests
    ├── test_cli.py                  # CLI artifact creation tests
    ├── test_scout.py                # signal ingestion tests
    ├── test_cache.py                # disk cache tests
    └── test_normalize.py            # normalisation tests
```
