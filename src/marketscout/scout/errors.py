"""Scout module errors: single source for ScoutError."""

from __future__ import annotations


class ScoutError(Exception):
    """Raised when Scout fetch or parse fails (no fallback)."""

    pass
