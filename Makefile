# MarketScout — run from repo root after: pip install -e .

PYTHON ?= python

backend:
	uvicorn marketscout.backend.main:app --reload --port 8000

frontend:
	streamlit run src/marketscout/frontend/app.py

run: backend

test:
	$(PYTHON) -m pytest tests/ -q

clean:
	rm -rf out/ .cache/ .pytest_cache/

.PHONY: backend frontend run test clean
