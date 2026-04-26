"""New backend endpoint tests using httpx.AsyncClient and pytest-asyncio.

Tests:
  - POST /search  — mocked pipeline returns 200 with correct response shape
  - POST /ask     — missing database returns 503
  - POST /email   — missing SMTP config returns 200 with sent=False
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from marketscout.backend.main import app

_TRANSPORT = httpx.ASGITransport(app=app)
_BASE = "http://test"


async def test_search_returns_200_with_correct_shape() -> None:
    """POST /search with mocked pipeline returns 200 and the expected response shape."""
    mock_opps = [
        {"title": "Labor shortage", "pain_score": 7.5, "roi_signal": 8.0, "confidence": 0.65},
        {"title": "Permit delays",  "pain_score": 6.2, "roi_signal": 6.8, "confidence": 0.55},
    ]

    with patch(
        "marketscout.backend.main._execute_search_pipeline",
        return_value=(1714000000, mock_opps, 18),
    ):
        async with httpx.AsyncClient(transport=_TRANSPORT, base_url=_BASE) as ac:
            response = await ac.post(
                "/search",
                json={"city": "Vancouver", "industry": "Construction", "limit": 10},
            )

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data["run_id"], int)
    assert isinstance(data["opportunities"], list)
    assert isinstance(data["signal_count"], int)
    assert data["run_id"] == 1714000000
    assert len(data["opportunities"]) == 2
    assert data["signal_count"] == 18


async def test_ask_returns_503_when_db_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """POST /ask returns 503 when the Gold layer database file does not exist."""
    missing_db = tmp_path / "nonexistent.db"
    monkeypatch.setenv("MARKETSCOUT_DB_PATH", str(missing_db))

    async with httpx.AsyncClient(transport=_TRANSPORT, base_url=_BASE) as ac:
        response = await ac.post(
            "/ask",
            json={"question": "What are the top opportunities?", "run_id": 123},
        )

    assert response.status_code == 503
    assert "search" in response.json()["detail"].lower()


async def test_email_with_no_smtp_config_returns_sent_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """POST /email returns 200 with sent=False when SMTP env vars are not set."""
    monkeypatch.delenv("SMTP_USER", raising=False)
    monkeypatch.delenv("SMTP_APP_PASSWORD", raising=False)
    monkeypatch.delenv("BRIEFING_RECIPIENT", raising=False)

    async with httpx.AsyncClient(transport=_TRANSPORT, base_url=_BASE) as ac:
        response = await ac.post(
            "/email",
            json={
                "run_id": 123,
                "opportunities": [],
                "city": "Vancouver",
                "industry": "Construction",
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["sent"] is False
    assert len(data["detail"]) > 0
