"""Tests for the interactive terminal mode (marketscout/interactive.py)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from marketscout.interactive import (
    _handle_missing_adzuna_keys,
    check_adzuna_keys,
    prompt_api_key_setup,
    prompt_compare,
    prompt_history,
    prompt_opp_list,
    prompt_opp_set,
    prompt_run_analysis,
    run_menu,
)


# ── check_adzuna_keys ─────────────────────────────────────────────────────────

def test_check_adzuna_keys_false_when_both_missing(monkeypatch):
    monkeypatch.delenv("ADZUNA_APP_ID", raising=False)
    monkeypatch.delenv("ADZUNA_APP_KEY", raising=False)
    assert check_adzuna_keys() is False


def test_check_adzuna_keys_false_when_only_id_set(monkeypatch):
    monkeypatch.setenv("ADZUNA_APP_ID", "test-id")
    monkeypatch.delenv("ADZUNA_APP_KEY", raising=False)
    assert check_adzuna_keys() is False


def test_check_adzuna_keys_false_when_only_key_set(monkeypatch):
    monkeypatch.delenv("ADZUNA_APP_ID", raising=False)
    monkeypatch.setenv("ADZUNA_APP_KEY", "test-key")
    assert check_adzuna_keys() is False


def test_check_adzuna_keys_true_when_both_set(monkeypatch):
    monkeypatch.setenv("ADZUNA_APP_ID", "test-id")
    monkeypatch.setenv("ADZUNA_APP_KEY", "test-key")
    assert check_adzuna_keys() is True


# ── prompt_api_key_setup ──────────────────────────────────────────────────────

def test_api_key_setup_sets_all_three_env_vars(monkeypatch):
    monkeypatch.delenv("ADZUNA_APP_ID", raising=False)
    monkeypatch.delenv("ADZUNA_APP_KEY", raising=False)
    monkeypatch.delenv("ADZUNA_COUNTRY", raising=False)

    responses = iter(["my-app-id", "my-secret-key", "us"])
    with patch("builtins.input", side_effect=lambda _: next(responses)):
        result = prompt_api_key_setup()

    assert result == 0
    assert os.environ["ADZUNA_APP_ID"] == "my-app-id"
    assert os.environ["ADZUNA_APP_KEY"] == "my-secret-key"
    assert os.environ["ADZUNA_COUNTRY"] == "us"


def test_api_key_setup_keeps_existing_when_blank(monkeypatch):
    monkeypatch.setenv("ADZUNA_APP_ID", "existing-id")
    monkeypatch.setenv("ADZUNA_APP_KEY", "existing-key")

    with patch("builtins.input", return_value=""):
        prompt_api_key_setup()

    assert os.environ["ADZUNA_APP_ID"] == "existing-id"
    assert os.environ["ADZUNA_APP_KEY"] == "existing-key"


def test_api_key_setup_returns_zero():
    with patch("builtins.input", return_value=""):
        result = prompt_api_key_setup()
    assert result == 0


# ── _handle_missing_adzuna_keys ───────────────────────────────────────────────

def test_handle_missing_keys_switch_to_rss():
    with patch("builtins.input", return_value="2"):
        result = _handle_missing_adzuna_keys()
    assert result == "rss"


def test_handle_missing_keys_cancel_returns_none():
    with patch("builtins.input", return_value="3"):
        result = _handle_missing_adzuna_keys()
    assert result is None


def test_handle_missing_keys_enter_keys_success(monkeypatch):
    monkeypatch.setenv("ADZUNA_APP_ID", "new-id")
    monkeypatch.setenv("ADZUNA_APP_KEY", "new-key")

    # Choice "1" → setup, then check passes
    responses = iter(["1", "", "", ""])   # choice=1, then three blank inputs for setup
    with patch("builtins.input", side_effect=lambda _: next(responses)):
        result = _handle_missing_adzuna_keys()
    assert result == "adzuna"


def test_handle_missing_keys_enter_keys_still_missing(monkeypatch):
    monkeypatch.delenv("ADZUNA_APP_ID", raising=False)
    monkeypatch.delenv("ADZUNA_APP_KEY", raising=False)

    # Choice "1" → setup with blanks → keys still missing → falls back to rss
    responses = iter(["1", "", "", ""])
    with patch("builtins.input", side_effect=lambda _: next(responses)):
        result = _handle_missing_adzuna_keys()
    assert result == "rss"


# ── run_menu ──────────────────────────────────────────────────────────────────

def test_run_menu_exits_on_last_item():
    """Choice '7' (Exit) should return 0 immediately."""
    with patch("builtins.input", return_value="7"):
        assert run_menu() == 0


def test_run_menu_eof_returns_zero():
    with patch("builtins.input", side_effect=EOFError):
        assert run_menu() == 0


def test_run_menu_keyboard_interrupt_returns_zero():
    with patch("builtins.input", side_effect=KeyboardInterrupt):
        assert run_menu() == 0


def test_run_menu_non_numeric_input_then_exit():
    """Non-numeric input prints error but does not crash; '7' exits cleanly."""
    responses = iter(["abc", "7"])
    with patch("builtins.input", side_effect=lambda _: next(responses)):
        assert run_menu() == 0


def test_run_menu_out_of_range_then_exit():
    responses = iter(["99", "0", "7"])
    with patch("builtins.input", side_effect=lambda _: next(responses)):
        assert run_menu() == 0


def test_run_menu_blank_input_then_exit():
    """Blank input should be ignored; '7' exits cleanly."""
    responses = iter(["", "7"])
    with patch("builtins.input", side_effect=lambda _: next(responses)):
        assert run_menu() == 0


def test_run_menu_dispatches_to_history():
    """
    Choosing '2' (View run history) invokes cmd_history via prompt_history.
    Patch cmd_history at the interactive module level; verify it's called.
    """
    # inputs: menu choice "2", limit "10", then menu choice "7" to exit
    responses = iter(["2", "10", "7"])
    with patch("builtins.input", side_effect=lambda _: next(responses)), \
         patch("marketscout.interactive.cmd_history", return_value=0) as mock_hist:
        run_menu()
    mock_hist.assert_called_once_with(10)


# ── prompt_history ────────────────────────────────────────────────────────────

def test_prompt_history_calls_cmd_history_with_limit():
    with patch("builtins.input", return_value="5"), \
         patch("marketscout.interactive.cmd_history", return_value=0) as mock_hist:
        result = prompt_history()
    mock_hist.assert_called_once_with(5)
    assert result == 0


def test_prompt_history_defaults_to_10_on_bad_input():
    responses = iter(["not-a-number"])
    with patch("builtins.input", side_effect=lambda _: next(responses)), \
         patch("marketscout.interactive.cmd_history", return_value=0) as mock_hist:
        prompt_history()
    mock_hist.assert_called_once_with(10)


# ── prompt_compare ────────────────────────────────────────────────────────────

def test_prompt_compare_calls_cmd_compare():
    responses = iter(["Toronto", "Retail", "4"])
    with patch("builtins.input", side_effect=lambda _: next(responses)), \
         patch("marketscout.interactive.cmd_compare", return_value=0) as mock_cmp:
        result = prompt_compare()
    mock_cmp.assert_called_once_with("Toronto", "Retail", 4)
    assert result == 0


def test_prompt_compare_defaults_on_bad_limit():
    responses = iter(["Vancouver", "Construction", "oops"])
    with patch("builtins.input", side_effect=lambda _: next(responses)), \
         patch("marketscout.interactive.cmd_compare", return_value=0) as mock_cmp:
        prompt_compare()
    mock_cmp.assert_called_once_with("Vancouver", "Construction", 3)


# ── prompt_opp_list ────────────────────────────────────────────────────────────

def test_prompt_opp_list_no_filters_calls_cmd_opp_list():
    # blank, blank, blank (city, industry, status) then default limit
    responses = iter(["", "", "", "20"])
    with patch("builtins.input", side_effect=lambda _: next(responses)), \
         patch("marketscout.interactive.cmd_opp_list", return_value=0) as mock_list:
        result = prompt_opp_list()
    mock_list.assert_called_once_with(status=None, city=None, industry=None, limit=20)
    assert result == 0


def test_prompt_opp_list_with_valid_status():
    responses = iter(["Vancouver", "Construction", "prioritized", "10"])
    with patch("builtins.input", side_effect=lambda _: next(responses)), \
         patch("marketscout.interactive.cmd_opp_list", return_value=0) as mock_list:
        prompt_opp_list()
    mock_list.assert_called_once_with(status="prioritized", city="Vancouver", industry="Construction", limit=10)


def test_prompt_opp_list_unknown_status_becomes_none():
    responses = iter(["", "", "flying", "20"])
    with patch("builtins.input", side_effect=lambda _: next(responses)), \
         patch("marketscout.interactive.cmd_opp_list", return_value=0) as mock_list:
        prompt_opp_list()
    mock_list.assert_called_once_with(status=None, city=None, industry=None, limit=20)


# ── prompt_opp_set ─────────────────────────────────────────────────────────────

def test_prompt_opp_set_calls_cmd_opp_set():
    # opp_id, then status choice, then note
    responses = iter(["42", "prioritized", "strong signal"])
    with patch("builtins.input", side_effect=lambda _: next(responses)), \
         patch("marketscout.interactive.cmd_opp_set", return_value=0) as mock_set:
        result = prompt_opp_set()
    mock_set.assert_called_once_with(42, "prioritized", "strong signal")
    assert result == 0


def test_prompt_opp_set_no_note():
    responses = iter(["7", "rejected", ""])
    with patch("builtins.input", side_effect=lambda _: next(responses)), \
         patch("marketscout.interactive.cmd_opp_set", return_value=0) as mock_set:
        prompt_opp_set()
    mock_set.assert_called_once_with(7, "rejected", None)


def test_prompt_opp_set_invalid_id_returns_one():
    responses = iter(["not-a-number"])
    with patch("builtins.input", side_effect=lambda _: next(responses)):
        result = prompt_opp_set()
    assert result == 1


# ── prompt_run_analysis ────────────────────────────────────────────────────────

def test_prompt_run_analysis_rss_path(monkeypatch):
    """
    Full guided run with RSS provider — should call cmd_run with provider='rss'.
    """
    monkeypatch.delenv("ADZUNA_APP_ID", raising=False)
    monkeypatch.delenv("ADZUNA_APP_KEY", raising=False)

    # city, industry, provider, write_leads (Y), deterministic (N)
    responses = iter(["Vancouver", "Construction", "rss", "y", "n"])
    with patch("builtins.input", side_effect=lambda _: next(responses)), \
         patch("marketscout.interactive.cmd_run", return_value=0) as mock_run:
        result = prompt_run_analysis()

    assert result == 0
    mock_run.assert_called_once()
    _, kwargs = mock_run.call_args
    assert kwargs["jobs_provider"] == "rss"
    assert kwargs["city"] == "Vancouver"
    assert kwargs["industry"] == "Construction"


def test_prompt_run_analysis_adzuna_with_keys(monkeypatch):
    monkeypatch.setenv("ADZUNA_APP_ID", "id")
    monkeypatch.setenv("ADZUNA_APP_KEY", "key")

    responses = iter(["Vancouver", "Construction", "adzuna", "y", "n"])
    with patch("builtins.input", side_effect=lambda _: next(responses)), \
         patch("marketscout.interactive.cmd_run", return_value=0) as mock_run:
        prompt_run_analysis()

    _, kwargs = mock_run.call_args
    assert kwargs["jobs_provider"] == "adzuna"


def test_prompt_run_analysis_missing_keys_switch_to_rss(monkeypatch):
    """
    User picks adzuna but keys are missing; selects option 2 (RSS) in the
    missing-keys dialog. Analysis runs with rss.
    """
    monkeypatch.delenv("ADZUNA_APP_ID", raising=False)
    monkeypatch.delenv("ADZUNA_APP_KEY", raising=False)

    # city, industry, provider=adzuna → missing key dialog → "2" (rss) → write_leads, deterministic
    responses = iter(["Vancouver", "Construction", "adzuna", "2", "y", "n"])
    with patch("builtins.input", side_effect=lambda _: next(responses)), \
         patch("marketscout.interactive.cmd_run", return_value=0) as mock_run:
        result = prompt_run_analysis()

    assert result == 0
    _, kwargs = mock_run.call_args
    assert kwargs["jobs_provider"] == "rss"


def test_prompt_run_analysis_missing_keys_cancel(monkeypatch):
    """User picks adzuna, keys missing, then cancels — cmd_run is never called."""
    monkeypatch.delenv("ADZUNA_APP_ID", raising=False)
    monkeypatch.delenv("ADZUNA_APP_KEY", raising=False)

    responses = iter(["Vancouver", "Construction", "adzuna", "3"])
    with patch("builtins.input", side_effect=lambda _: next(responses)), \
         patch("marketscout.interactive.cmd_run", return_value=0) as mock_run:
        result = prompt_run_analysis()

    assert result == 0
    mock_run.assert_not_called()


# ── CLI no-subcommand / menu subcommand ───────────────────────────────────────

def _src_env(**extra) -> dict:
    src = str(Path(__file__).parent.parent / "src")
    env = dict(os.environ)
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{src}:{existing}" if existing else src
    env.update(extra)
    return env


def test_cli_menu_subcommand_invokes_interactive():
    """
    `marketscout menu` should launch interactive mode.
    We pipe '7\n' (Exit) via stdin so it exits cleanly.
    """
    result = subprocess.run(
        [sys.executable, "-m", "marketscout", "menu"],
        input="7\n",
        capture_output=True,
        text=True,
        env=_src_env(),
    )
    assert result.returncode == 0, result.stderr


def test_cli_no_subcommand_invokes_interactive():
    """
    `marketscout` with no arguments should launch interactive mode.
    We pipe '7\n' (Exit) via stdin so it exits cleanly.
    """
    result = subprocess.run(
        [sys.executable, "-m", "marketscout"],
        input="7\n",
        capture_output=True,
        text=True,
        env=_src_env(),
    )
    assert result.returncode == 0, result.stderr
