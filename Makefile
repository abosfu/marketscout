# MarketScout — Zero-Friction Strategy Engine (CLI)
# Run from repo root: make run | make test | make scout

PYTHON ?= python

run:
	PYTHONPATH=src $(PYTHON) -m marketscout run --industry Construction --objective "Market entry" --city Vancouver --location "Vancouver, BC"

test:
	PYTHONPATH=src $(PYTHON) -m pytest tests/ -v

scout:
	PYTHONPATH=src $(PYTHON) -m marketscout scout --city Vancouver --industry Construction --include-jobs

.PHONY: run test scout
