# MarketScout — Zero-Friction Strategy Engine (CLI)
# Run from repo root: make run | make test | make clean

PYTHON ?= python

run:
	PYTHONPATH=src $(PYTHON) -m marketscout run --city Vancouver --industry Construction

test:
	PYTHONPATH=src $(PYTHON) -m pytest tests/ -v

clean:
	rm -rf out/ .cache/ .pytest_cache/

.PHONY: run test clean
