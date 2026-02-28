# GitHub Release Checklist

Use this before tagging a new release (e.g. v1.0.0).

## Pre-release

- [ ] All tests pass: `make test` (or `PYTHONPATH=src pytest tests/ -v`)
- [ ] CLI run works: `make run` or `python -m marketscout run --industry Construction --objective "Market entry" --city Vancouver --location "Vancouver, BC"` (requires network or valid cache)
- [ ] CLI demo (dev-only): `python -m marketscout demo` creates `data/demo_input.json` and `data/demo_strategy.json`
- [ ] Dependencies are minimal and pinned in `requirements.txt` (no optional heavy deps required for core run)
- [ ] `CHANGELOG.md` updated with version and date

## Tag and release

- [ ] Bump version in `pyproject.toml` / `src/marketscout/__init__.py` if applicable
- [ ] Commit all changes with a clear message (e.g. `release: v1.0.0 — demo mode, HTML export, Streamlit Cloud entrypoint, docs`)
- [ ] Create tag: `git tag -a v1.0.0 -m "Release v1.0.0"`
- [ ] Push branch and tags: `git push && git push --tags`
- [ ] On GitHub: **Releases** → **Draft a new release** → choose tag `v1.0.0`, paste release notes from `CHANGELOG.md`
- [ ] Publish release

## Post-release

- [ ] Verify `python -m marketscout run` succeeds with network (or with valid cache)
