"""Configuration layer: defaults for city, headlines, cache TTL, strategy mode, and disk cache.

`load_dotenv()` is called once at import time so that a `.env` file at the project root
is transparently picked up by every os.environ / os.getenv call in the application.
Variables already present in the environment always take precedence (override=False).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv

# Load .env from the project root (two levels up from this file: src/marketscout/ → root).
# Safe to call repeatedly — dotenv is idempotent and never overwrites real env vars.
_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(dotenv_path=_ENV_FILE, override=False)

StrategyMode = Literal["mock", "llm", "auto"]

# Defaults (env overrides below)
DEFAULT_CITY = "Vancouver"
DEFAULT_MAX_HEADLINES = 10
DEFAULT_DISK_CACHE_TTL_SECONDS = 3600  # 1 hour for .cache/marketscout
DEFAULT_STRATEGY_MODE: StrategyMode = "auto"


def _env_int(key: str, default: int) -> int:
    """Read an integer from the environment; silently fall back to default on missing or invalid value."""
    try:
        val = os.environ.get(key)
        return int(val) if val is not None else default
    except ValueError:
        return default


def _env_mode(key: str, default: StrategyMode) -> StrategyMode:
    """Read a StrategyMode literal from the environment; return default for unrecognised values."""
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


def get_db_path() -> Path:
    """Path to the MarketScout SQLite database. Override with MARKETSCOUT_DB_PATH."""
    val = os.environ.get("MARKETSCOUT_DB_PATH")
    if val and val.strip():
        return Path(val.strip())
    return get_cache_dir() / "marketscout.db"


def get_google_api_key() -> str:
    """Gemini API key for NL2SQL. Set via GOOGLE_API_KEY."""
    return (os.environ.get("GOOGLE_API_KEY") or "").strip()


def get_smtp_config() -> dict:
    """SMTP credentials for email briefings. Returns dict with None values for unset keys.

    Keys: smtp_user, smtp_app_password, briefing_recipient.
    All three must be non-None to send email.
    """
    return {
        "smtp_user": os.environ.get("SMTP_USER") or None,
        "smtp_app_password": os.environ.get("SMTP_APP_PASSWORD") or None,
        "briefing_recipient": os.environ.get("BRIEFING_RECIPIENT") or None,
    }
