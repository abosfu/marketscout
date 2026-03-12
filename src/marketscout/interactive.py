"""Interactive terminal mode for MarketScout.

Shows a guided menu that wraps the existing CLI commands.
No extra dependencies — uses only builtins.input() and rich (already required).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from marketscout import __version__
from marketscout.cli import (
    _default_out_dir,
    cmd_compare,
    cmd_history,
    cmd_opp_list,
    cmd_opp_set,
    cmd_run,
)
from marketscout.db import VALID_STATUSES
from marketscout.normalize import SUPPORTED_INDUSTRIES


# ── Low-level input helpers ───────────────────────────────────────────────────

def _prompt(text: str, default: str | None = None, choices: list[str] | None = None) -> str:
    """Input prompt with optional default and choice validation. Loops until valid."""
    hint = ""
    if choices:
        hint = f" [{'/'.join(choices)}]"
    elif default is not None:
        hint = f" [{default}]"

    while True:
        raw = input(f"{text}{hint}: ").strip()
        if not raw:
            if default is not None:
                return default
            continue
        if choices and raw.lower() not in [c.lower() for c in choices]:
            print(f"  Please choose one of: {', '.join(choices)}")
            continue
        return raw


def _confirm(text: str, default: bool = True) -> bool:
    """Y/n confirmation prompt."""
    hint = "Y/n" if default else "y/N"
    raw = input(f"{text} [{hint}]: ").strip().lower()
    if not raw:
        return default
    return raw in ("y", "yes")


def _print_header() -> None:
    try:
        from rich.console import Console
        Console().print(f"\n[bold]MarketScout v{__version__}[/bold] — Interactive Mode\n")
    except ImportError:
        print(f"\nMarketScout v{__version__} — Interactive Mode\n")


def _section(title: str) -> None:
    print(f"\n── {title} ──\n")


# ── Adzuna key handling ───────────────────────────────────────────────────────

def check_adzuna_keys() -> bool:
    """Return True if both Adzuna API keys are present in the environment."""
    return bool(os.environ.get("ADZUNA_APP_ID")) and bool(os.environ.get("ADZUNA_APP_KEY"))


def prompt_api_key_setup() -> int:
    """Let the user enter Adzuna API keys into os.environ for the current session."""
    _section("API Key Setup (session only — keys are not written to disk)")

    def _status(key: str) -> str:
        return "[set]" if os.environ.get(key) else "[not set]"

    print(f"  ADZUNA_APP_ID:  {_status('ADZUNA_APP_ID')}")
    print(f"  ADZUNA_APP_KEY: {_status('ADZUNA_APP_KEY')}")
    print(f"  ADZUNA_COUNTRY: {os.environ.get('ADZUNA_COUNTRY', 'ca')}\n")

    val = input("ADZUNA_APP_ID (leave blank to keep current): ").strip()
    if val:
        os.environ["ADZUNA_APP_ID"] = val

    val = input("ADZUNA_APP_KEY (leave blank to keep current): ").strip()
    if val:
        os.environ["ADZUNA_APP_KEY"] = val

    default_country = os.environ.get("ADZUNA_COUNTRY", "ca")
    val = input(f"ADZUNA_COUNTRY [{default_country}]: ").strip()
    if val:
        os.environ["ADZUNA_COUNTRY"] = val

    print("\n  Keys updated for this session.")
    print("  Tip: add them to a .env file and source it to persist between sessions.")
    return 0


def _handle_missing_adzuna_keys() -> str | None:
    """
    Called when Adzuna is selected but keys are missing.
    Returns the provider to use ('adzuna' or 'rss'), or None to cancel.
    """
    print("\n  Adzuna API keys not found in environment.")
    print("  1. Enter keys now (session only)")
    print("  2. Switch to RSS provider (no API key required)")
    print("  3. Cancel\n")

    choice = input("Choice [1/2/3]: ").strip()

    if choice == "1":
        prompt_api_key_setup()
        if check_adzuna_keys():
            return "adzuna"
        print("  Keys still missing. Switching to RSS.")
        return "rss"
    elif choice == "2":
        return "rss"
    else:
        return None


# ── Guided flows ──────────────────────────────────────────────────────────────

def prompt_run_analysis() -> int:
    """Guided 'Run new analysis' flow."""
    _section("Run New Analysis")

    city = _prompt("City", default="Vancouver")

    print("Supported industries:")
    for ind in sorted(SUPPORTED_INDUSTRIES):
        print(f"  • {ind}")
    industry = _prompt("\nIndustry", default="Construction")

    provider = _prompt("Jobs provider", default="adzuna", choices=["adzuna", "rss"])
    if provider == "adzuna" and not check_adzuna_keys():
        provider = _handle_missing_adzuna_keys()
        if provider is None:
            print("  Cancelled.")
            return 0

    write_leads = _confirm("Write leads.csv?", default=True)
    deterministic = _confirm("Deterministic mode (reproducible output)?", default=False)

    out_dir = _default_out_dir(city, industry)
    print(f"\n  Running: {city} / {industry} …\n")

    return cmd_run(
        city=city,
        industry=industry,
        out_dir=out_dir,
        jobs_limit=10,
        headlines_limit=10,
        jobs_provider=provider,
        allow_provider_fallback=(provider == "adzuna"),
        write_leads=write_leads,
        refresh=False,
        deterministic=deterministic,
    )


def prompt_history() -> int:
    """Guided 'View run history' flow."""
    _section("Run History")
    limit_str = _prompt("Number of recent runs to show", default="10")
    try:
        limit = int(limit_str)
    except ValueError:
        limit = 10
    return cmd_history(limit)


def prompt_compare() -> int:
    """Guided 'Compare runs' flow."""
    _section("Compare Runs")
    city = _prompt("City", default="Vancouver")
    industry = _prompt("Industry", default="Construction")
    limit_str = _prompt("Number of runs to aggregate", default="3")
    try:
        limit = int(limit_str)
    except ValueError:
        limit = 3
    return cmd_compare(city, industry, limit)


def prompt_opp_list() -> int:
    """Guided 'View opportunities' flow."""
    _section("View Opportunities")
    print("Leave blank to show all.\n")

    city = input("Filter by city: ").strip() or None
    industry = input("Filter by industry: ").strip() or None

    print(f"Valid statuses: {', '.join(VALID_STATUSES)}")
    status = input("Filter by status: ").strip() or None
    if status and status not in VALID_STATUSES:
        print(f"  Unknown status '{status}' — showing all.")
        status = None

    limit_str = _prompt("Max results", default="20")
    try:
        limit = int(limit_str)
    except ValueError:
        limit = 20

    return cmd_opp_list(status=status, city=city, industry=industry, limit=limit)


def prompt_opp_set() -> int:
    """Guided 'Update opportunity status' flow."""
    _section("Update Opportunity Status")
    print("Run 'View opportunities' first to find the ID.\n")

    opp_id_str = _prompt("Opportunity ID")
    try:
        opp_id = int(opp_id_str)
    except ValueError:
        print("  Invalid ID — must be a number.")
        return 1

    status = _prompt(
        "New status",
        choices=list(VALID_STATUSES),
        default="under_review",
    )
    note = input("Note (optional, press Enter to skip): ").strip() or None

    return cmd_opp_set(opp_id, status, note)


# ── Main menu ─────────────────────────────────────────────────────────────────

_MENU_LABELS = [
    "Run a new analysis",
    "View run history",
    "Compare runs",
    "View opportunities",
    "Update opportunity status",
    "Setup API keys (session only)",
    "Exit",
]

_MENU_FNS = [
    prompt_run_analysis,
    prompt_history,
    prompt_compare,
    prompt_opp_list,
    prompt_opp_set,
    prompt_api_key_setup,
    None,  # Exit
]


def run_menu() -> int:
    """
    Show the interactive menu and dispatch to guided flows.
    Loops until the user chooses Exit or sends EOF / KeyboardInterrupt.
    """
    _print_header()

    while True:
        print()
        for i, label in enumerate(_MENU_LABELS, 1):
            print(f"  {i}. {label}")

        try:
            raw = input("\nChoice: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0

        if not raw:
            continue

        try:
            idx = int(raw) - 1
        except ValueError:
            print("  Please enter a number.")
            continue

        if idx < 0 or idx >= len(_MENU_LABELS):
            print(f"  Please enter a number between 1 and {len(_MENU_LABELS)}.")
            continue

        fn = _MENU_FNS[idx]
        if fn is None:          # Exit
            print("  Goodbye.")
            return 0

        try:
            fn()
        except KeyboardInterrupt:
            print("\n  (interrupted)")
        except Exception as e:
            print(f"  Error: {e}", file=sys.stderr)
