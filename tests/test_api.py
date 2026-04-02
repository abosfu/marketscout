"""API tests: root health check and NL2SQL /api/ask endpoint.

All LangChain/Gemini calls are monkeypatched so no real API key or database
is required during CI.  The internal helper `_run_nl2sql_pipeline` is the
single patch point for the happy-path tests; other tests exercise the
pre-flight guard logic without touching the pipeline at all.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from marketscout.backend.main import app
from marketscout.backend.nl2sql import _check_safety

client = TestClient(app)

# Canonical mock return value reused across happy-path tests
_MOCK_SQL = "SELECT title, pain_score FROM opportunities ORDER BY pain_score DESC LIMIT 5;"
_MOCK_INSIGHTS = (
    "The top five opportunities cluster around procurement automation, "
    "each scoring above 8.0 on pain — strong signal for near-term investment."
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _ask(question: str = "Which opportunities have an urgency score over 8.0?") -> dict:
    """POST /api/ask and return the parsed JSON body."""
    return client.post("/api/ask", json={"user_question": question})


# ── Root endpoint ─────────────────────────────────────────────────────────────

def test_root_returns_running_status() -> None:
    """GET / returns 200 with the expected status and version fields."""
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "MarketScout API is running"
    assert data["version"] == "2.0"


# ── Pre-flight guards (no pipeline needed) ────────────────────────────────────

def test_ask_returns_503_when_api_key_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """POST /api/ask returns 503 when GOOGLE_API_KEY is not set."""
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    response = _ask()
    assert response.status_code == 503
    assert "GOOGLE_API_KEY" in response.json()["detail"]


def test_ask_returns_500_when_database_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """POST /api/ask returns 500 when the SQLite database does not exist."""
    monkeypatch.setenv("GOOGLE_API_KEY", "fake-key-for-test")
    # The endpoint imports get_db_path from marketscout.config at call time.
    missing_db = tmp_path / "nonexistent.db"
    with patch("marketscout.config.get_db_path", return_value=missing_db):
        response = _ask()
    assert response.status_code == 500
    assert "not found" in response.json()["detail"].lower()


# ── Happy path (pipeline fully mocked) ───────────────────────────────────────

def test_ask_returns_sql_and_insights_when_pipeline_mocked(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """POST /api/ask returns 200 with sql_query and insights when the pipeline is mocked."""
    monkeypatch.setenv("GOOGLE_API_KEY", "fake-key-for-test")
    fake_db = tmp_path / "marketscout.db"
    fake_db.touch()  # file must exist for the pre-flight check

    with (
        patch("marketscout.config.get_db_path", return_value=fake_db),
        patch(
            "marketscout.backend.nl2sql._run_nl2sql_pipeline",
            return_value=(_MOCK_SQL, _MOCK_INSIGHTS),
        ),
    ):
        response = _ask("Which opportunities have an urgency score over 8.0?")

    assert response.status_code == 200
    data = response.json()
    assert data["sql_query"] == _MOCK_SQL
    assert data["insights"] == _MOCK_INSIGHTS


def test_ask_response_contains_select_and_non_empty_insights(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """sql_query contains SELECT and insights is a non-empty string."""
    monkeypatch.setenv("GOOGLE_API_KEY", "fake-key-for-test")
    fake_db = tmp_path / "marketscout.db"
    fake_db.touch()

    with (
        patch("marketscout.config.get_db_path", return_value=fake_db),
        patch(
            "marketscout.backend.nl2sql._run_nl2sql_pipeline",
            return_value=(_MOCK_SQL, _MOCK_INSIGHTS),
        ),
    ):
        response = _ask()

    assert response.status_code == 200
    data = response.json()
    assert "SELECT" in data["sql_query"]
    assert len(data["insights"]) > 0


# ── Safety guard ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("dangerous_sql", [
    "DROP TABLE opportunities;",
    "DELETE FROM runs WHERE 1=1;",
    "UPDATE opportunities SET pain_score = 0;",
    "INSERT INTO runs (city) VALUES ('hack');",
    # Mixed case
    "drop table runs;",
    "Delete from leads;",
])
def test_check_safety_raises_on_dangerous_sql(dangerous_sql: str) -> None:
    """_check_safety raises HTTP 400 for any SQL containing write/DDL keywords."""
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        _check_safety(dangerous_sql)
    assert exc_info.value.status_code == 400
    assert "Unsafe query detected" in exc_info.value.detail


def test_check_safety_passes_for_select() -> None:
    """_check_safety does not raise for a plain SELECT query."""
    _check_safety("SELECT title, pain_score FROM opportunities LIMIT 5;")


def test_ask_returns_400_when_pipeline_returns_unsafe_sql(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """POST /api/ask returns 400 if the LLM somehow generates a DROP statement."""
    monkeypatch.setenv("GOOGLE_API_KEY", "fake-key-for-test")
    fake_db = tmp_path / "marketscout.db"
    fake_db.touch()

    def _unsafe_pipeline(question: str, db_path: str, api_key: str):
        # Simulate an LLM that generated a dangerous query
        _check_safety("DROP TABLE opportunities;")

    with (
        patch("marketscout.config.get_db_path", return_value=fake_db),
        patch("marketscout.backend.nl2sql._run_nl2sql_pipeline", side_effect=_unsafe_pipeline),
    ):
        response = _ask("Drop everything")

    assert response.status_code == 400
    assert "Unsafe query detected" in response.json()["detail"]


# ── Pipeline error handling ───────────────────────────────────────────────────

def test_ask_returns_500_when_pipeline_raises_unexpected_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """POST /api/ask wraps unexpected pipeline exceptions in a 500 response."""
    monkeypatch.setenv("GOOGLE_API_KEY", "fake-key-for-test")
    fake_db = tmp_path / "marketscout.db"
    fake_db.touch()

    with (
        patch("marketscout.config.get_db_path", return_value=fake_db),
        patch(
            "marketscout.backend.nl2sql._run_nl2sql_pipeline",
            side_effect=RuntimeError("LLM quota exceeded"),
        ),
    ):
        response = _ask()

    assert response.status_code == 500
    assert "LLM quota exceeded" in response.json()["detail"]
