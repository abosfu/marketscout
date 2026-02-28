"""Disk cache: keying, TTL, read/write."""

import json
import time
from datetime import date
from pathlib import Path

import pytest

from marketscout.cache import cache_key, cache_path, is_cache_valid, read_cached, write_cached


def test_cache_key_deterministic() -> None:
    """Cache key is deterministic for (city, industry, date)."""
    k1 = cache_key("Vancouver", "Construction", date(2025, 2, 27))
    k2 = cache_key("Vancouver", "Construction", date(2025, 2, 27))
    assert k1 == k2
    assert "vancouver" in k1 and "construction" in k1 and "2025-02-27" in k1


def test_cache_key_sanitizes_spaces() -> None:
    """Spaces in city/industry are replaced for filesystem safety."""
    k = cache_key("New York", "Real Estate")
    assert " " not in k


def test_cache_path_suffix() -> None:
    """cache_path returns path with correct suffix."""
    p = cache_path(Path("/tmp"), "vancouver_construction_2025-02-27", "headlines.json")
    assert p.name == "vancouver_construction_2025-02-27.headlines.json"


def test_is_cache_valid_missing_false(tmp_path: Path) -> None:
    """Missing file is not valid."""
    assert is_cache_valid(tmp_path / "nonexistent.json", 3600) is False


def test_is_cache_valid_expired_false(tmp_path: Path) -> None:
    """Expired file (mtime older than TTL) is not valid."""
    f = tmp_path / "f.json"
    f.write_text("{}")
    # TTL 1 second; age the file by 2 seconds
    old = time.time() - 2
    try:
        import os
        os.utime(f, (old, old))
    except Exception:
        pytest.skip("utime not available")
    assert is_cache_valid(f, 1) is False


def test_is_cache_valid_fresh_true(tmp_path: Path) -> None:
    """Fresh file is valid."""
    f = tmp_path / "f.json"
    f.write_text("[]")
    assert is_cache_valid(f, 3600) is True


def test_write_and_read_cached(tmp_path: Path) -> None:
    """write_cached then read_cached returns same data within TTL."""
    data = [{"title": "A", "link": "https://a.com"}]
    write_cached(tmp_path, "key1", "headlines.json", data)
    out = read_cached(tmp_path, "key1", "headlines.json", ttl_seconds=3600)
    assert out == data
