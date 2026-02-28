"""Disk cache for Scout data: keyed by (city, industry, date), configurable TTL."""

from __future__ import annotations

import json
import time
from datetime import date
from pathlib import Path
from typing import Any

from marketscout.config import get_cache_dir, get_disk_cache_ttl_seconds


def cache_key(city: str, industry: str, d: date | None = None) -> str:
    """Return a filesystem-safe cache key for (city, industry, date)."""
    d = d or date.today()
    parts = [city.strip().lower().replace(" ", "_"), industry.strip().lower().replace(" ", "_"), d.isoformat()]
    return "_".join(parts)


def cache_path(cache_dir: Path, key: str, suffix: str) -> Path:
    """Path for a cache file: cache_dir/key.suffix."""
    return cache_dir / f"{key}.{suffix}"


def is_cache_valid(path: Path, ttl_seconds: int) -> bool:
    """Return True if path exists and mtime is within ttl_seconds from now."""
    if not path.exists():
        return False
    mtime = path.stat().st_mtime
    now = time.time()
    return (now - mtime) <= ttl_seconds


def read_cached(cache_dir: Path, key: str, suffix: str, ttl_seconds: int) -> Any | None:
    """
    Read cached JSON if present and not expired.
    Returns decoded data or None if missing/expired/invalid.
    """
    path = cache_path(cache_dir, key, suffix)
    if not is_cache_valid(path, ttl_seconds):
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def write_cached(cache_dir: Path, key: str, suffix: str, data: Any) -> None:
    """Write data as JSON to cache_dir/key.suffix. Creates cache_dir if needed."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_path(cache_dir, key, suffix)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
