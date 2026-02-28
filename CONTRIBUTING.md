# Contributing to MarketScout

Thanks for your interest in contributing.

## Setup

```bash
git clone <repo-url>
cd marketscout
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pip install -e ".[dev]"
```

## Running tests

```bash
make test
# or
PYTHONPATH=src pytest tests/ -v
```

## Code style

- Use type hints and docstrings for public functions.
- Keep functions small and testable.
- Prefer the existing patterns: Scout (headlines), Brain (strategy + schema), App (Streamlit).

## Submitting changes

1. Open an issue or pick an existing one.
2. Branch from `main`, make your changes, add tests if applicable.
3. Ensure `make test` passes.
4. Open a pull request with a short description of the change.

## Scope

MarketScout stays minimal: 3-click UX, Scout → Brain → structured JSON → UI. New features (e.g. Jobs, FRED, Next.js) are planned separately; large redesigns should be discussed in an issue first.
