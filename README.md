# MarketScout

A live market intelligence system that surfaces real B2B targets from Google Jobs and news data — showing which companies are hiring, what pain they're signaling, and what to pitch them.

## What It Does

The user types any city and any industry. The system fetches live job postings from Google Jobs via SerpAPI and industry news via NewsAPI in real time. A Groq LLM reads the actual signals and derives pain categories, opportunity scores, and pitch recommendations per company. A plain-English chat lets users query the run's data without writing SQL.

## Architecture

Medallion pipeline:

- **Bronze** — raw job postings (SerpAPI dual-query) and headlines (NewsAPI)
- **Silver** — deduplicated, validated, run-stamped signals
- **Gold** — SQLite star schema (`dim_runs`, `dim_signals`, `dim_opportunities`, `fact_leads`)

FastAPI backend — `/search` and `/ask` endpoints
Streamlit frontend — clean monospace dashboard
Groq — powers both strategy generation and NL2SQL
SQLite — persistent Gold DB per run

## Features

- Any city, any industry — no hardcoded templates
- 10 target companies per search ranked by hiring urgency
- Company intelligence: what they're hiring for, what to pitch
- Market context: real industry-specific headlines
- NL2SQL chat: ask plain English questions about the current run
- Read-only DB safety: SQL blocklist + read-only SQLite URI

## Getting Started

### Requirements

Python 3.9+

### Install

```bash
git clone https://github.com/abosfu/marketscout
cd marketscout
pip install -e .
```

### Environment Variables

Create a `.env` file in the project root:

```
SERPAPI_KEY=your_serpapi_key
NEWSAPI_KEY=your_newsapi_key
GROQ_API_KEY=your_groq_key
```

### Run

Terminal 1 — Backend:

```bash
uvicorn marketscout.backend.main:app --reload --port 8000
```

Terminal 2 — Frontend:

```bash
streamlit run src/marketscout/frontend/app.py
```

Open http://localhost:8501

## Example Searches

- **Vancouver + Construction** → AtkinsRéalis, Turner Construction, Axiom Builders
- **Calgary + Banking** → CIBC, RBC, TD, Scotiabank, BMO, Neo Financial, ATB Financial
- **Vancouver + Project Management** → AtkinsRéalis, Robert Half, Stantec, GHD Group, TELUS, Demonware
- **Vancouver + Delivery** → Uber, DoorDash, Skip the Dishes, Canada Post, Sysco Canada

## NL2SQL Examples

After running a search, ask:

- "Which company has the most hiring signals?"
- "Tell me more about the TELUS work"
- "What is DoorDash hiring for?"

## Tests

```bash
pytest tests/ -q
```

114 passed, 1 skipped

## Tech Stack

Python, FastAPI, SQLite, SQLAlchemy, Streamlit, SerpAPI, NewsAPI, Groq, Pydantic, pytest

## Security

- SQL keyword blocklist rejects any write operation
- Read-only SQLite URI connection
- All queries scoped to current `run_id`
- API keys stored in `.env` only, never committed
