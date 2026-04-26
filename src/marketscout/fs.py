"""Filesystem helpers: project root resolution and run directory utilities."""

from __future__ import annotations

from pathlib import Path


def project_root() -> Path:
    """Return the absolute path of the project root directory (two levels above src/marketscout/)."""
    return Path(__file__).resolve().parents[2]


def find_latest_run_dir(base_out_dir: str | Path = "out") -> Path | None:
    """
    Return the run directory under base_out_dir with the most recent mtime, or None if none.

    A "run directory" is a direct child of base_out_dir (e.g. out/Vancouver_Construction_2025-02-27).
    Choosen by directory modification time (most recent first).
    """
    base = Path(base_out_dir).resolve()
    if not base.is_dir():
        return None
    candidates: list[Path] = []
    for p in base.iterdir():
        if p.is_dir() and not p.name.startswith("."):
            candidates.append(p)
    if not candidates:
        return None
    return max(candidates, key=lambda d: d.stat().st_mtime)
