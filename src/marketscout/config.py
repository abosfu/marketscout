"""Configuration layer: defaults for city, headlines, cache TTL, strategy mode, and disk cache."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

StrategyMode = Literal["mock", "llm", "auto"]

# Defaults (env overrides below)
DEFAULT_CITY = "Vancouver"
DEFAULT_MAX_HEADLINES = 10
DEFAULT_DISK_CACHE_TTL_SECONDS = 3600  # 1 hour for .cache/marketscout
DEFAULT_STRATEGY_MODE: StrategyMode = "auto"


def _env_int(key: str, default: int) -> int:
    try:
        val = os.environ.get(key)
        return int(val) if val is not None else default
    except ValueError:
        return default


def _env_mode(key: str, default: StrategyMode) -> StrategyMode:
    val = (os.environ.get(key) or "").strip().lower()
    if val in ("mock", "llm", "auto"):
        return val  # type: ignore[return-value]
    return default


def get_default_city() -> str:
    """Default city for RSS query (e.g. Vancouver). Override with MARKETSCOUT_DEFAULT_CITY."""
    return (os.environ.get("MARKETSCOUT_DEFAULT_CITY") or DEFAULT_CITY).strip() or DEFAULT_CITY


def get_max_headlines() -> int:
    """Max headlines to fetch. Override with MARKETSCOUT_MAX_HEADLINES."""
    return _env_int("MARKETSCOUT_MAX_HEADLINES", DEFAULT_MAX_HEADLINES)


def get_disk_cache_ttl_seconds() -> int:
    """Disk cache TTL in seconds for .cache/marketscout. Override with MARKETSCOUT_DISK_CACHE_TTL."""
    return _env_int("MARKETSCOUT_DISK_CACHE_TTL", DEFAULT_DISK_CACHE_TTL_SECONDS)


def get_strategy_mode() -> StrategyMode:
    """Strategy mode: mock, llm, or auto. Override with MARKETSCOUT_MODE."""
    return _env_mode("MARKETSCOUT_MODE", DEFAULT_STRATEGY_MODE)


def get_cache_dir() -> Path:
    """Base directory for disk cache. Default: .cache/marketscout (relative to cwd). Override with MARKETSCOUT_CACHE_DIR."""
    val = os.environ.get("MARKETSCOUT_CACHE_DIR")
    if val and val.strip():
        return Path(val.strip())
    return Path.cwd() / ".cache" / "marketscout"
