"""CLI entrypoint: python -m marketscout run | eval | bundle."""

from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import sys
import time
import uuid
import zipfile
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from marketscout import __version__
from marketscout.fs import find_latest_run_dir
from marketscout.normalize import SUPPORTED_INDUSTRIES, normalize_city, normalize_industry


def _slugify(text: str, max_len: int = 30) -> str:
    """Convert arbitrary text to a safe filesystem slug (lowercase, underscores)."""
    slug = re.sub(r"[^a-z0-9]+", "_", text.strip().lower()).strip("_")
    return (slug or "unknown")[:max_len]


def _default_out_dir(city: str, industry: str) -> Path:
    """Default output directory: out/<city>_<industry>_<YYYY-MM-DD>/"""
    date_str = datetime.now().strftime("%Y-%m-%d")
    return Path("out") / f"{_slugify(city)}_{_slugify(industry)}_{date_str}"


def _validate_and_normalize(city: str, industry: str) -> tuple[str, str] | None:
    """
    Normalize city and industry; validate industry against the supported list.
    Returns (canonical_city, canonical_industry) or None (and prints error) if invalid.
    """
    canonical_city = normalize_city(city)
    canonical_industry = normalize_industry(industry)
    if canonical_industry is None:
        available = ", ".join(sorted(SUPPORTED_INDUSTRIES))
        print(
            f"Error: unrecognised industry '{industry}'.\n"
            f"Supported industries: {available}\n"
            f"Tip: industry matching is case-insensitive and accepts common aliases "
            f"(e.g. 'tech' → Technology, 'health care' → Healthcare).",
            file=sys.stderr,
        )
        return None
    return canonical_city, canonical_industry


def _make_fetch_entry(provider: str, status: str, error: str | None = None) -> dict:
    return {"provider": provider, "status": status, "error": error}


def _fetch_signals(
    city: str,
    industry: str,
    headlines_limit: int,
    jobs_limit: int,
    jobs_provider: str,
    allow_provider_fallback: bool,
    refresh: bool,
    cache_dir: Path,
    ttl: int,
    err_console,
) -> tuple[list, list, dict] | None:
    """
    Fetch headlines and jobs; record per-source fetch status.

    When refresh=False (default): fall back to disk cache if a live fetch fails.
    When refresh=True: never use stale cache — fail hard if the live fetch fails.

    Returns (headlines, jobs, fetch_status) or None if unrecoverable.
    """
    from marketscout.cache import cache_key, read_cached, write_cached
    from marketscout.scout import ScoutError, fetch_headlines, fetch_jobs

    key = cache_key(city, industry)
    fetch_status: dict = {}

    # Headlines
    try:
        headlines = fetch_headlines(city=city, industry=industry, limit=headlines_limit)
        write_cached(cache_dir, key, "headlines.json", headlines)
        fetch_status["headlines"] = _make_fetch_entry("google_news_rss", "live")
    except ScoutError as e:
        if not refresh:
            cached = read_cached(cache_dir, key, "headlines.json", ttl)
            if cached is not None and isinstance(cached, list):
                headlines = cached
                fetch_status["headlines"] = _make_fetch_entry("google_news_rss", "cached", str(e))
                err_console.print("[yellow]Headlines: live fetch failed — using disk cache.[/yellow]")
            else:
                fetch_status["headlines"] = _make_fetch_entry("google_news_rss", "failed", str(e))
                err_console.print(f"[red]Error: headlines fetch failed and no cache available: {e}[/red]")
                return None
        else:
            fetch_status["headlines"] = _make_fetch_entry("google_news_rss", "failed", str(e))
            err_console.print(f"[red]Error: headlines fetch failed (--refresh disables cache fallback): {e}[/red]")
            return None

    # Jobs
    try:
        jobs = fetch_jobs(
            city=city, industry=industry, limit=jobs_limit,
            provider=jobs_provider, allow_fallback=allow_provider_fallback,
        )
        write_cached(cache_dir, key, "jobs.json", jobs)
        fetch_status["jobs"] = _make_fetch_entry(jobs_provider, "live")
    except ScoutError as e:
        if not refresh:
            cached = read_cached(cache_dir, key, "jobs.json", ttl)
            if cached is not None and isinstance(cached, list):
                jobs = cached
                fetch_status["jobs"] = _make_fetch_entry(jobs_provider, "cached", str(e))
                err_console.print("[yellow]Jobs: live fetch failed — using disk cache.[/yellow]")
            else:
                fetch_status["jobs"] = _make_fetch_entry(jobs_provider, "failed", str(e))
                err_console.print(f"[red]Error: jobs fetch failed and no cache available: {e}[/red]")
                return None
        else:
            fetch_status["jobs"] = _make_fetch_entry(jobs_provider, "failed", str(e))
            err_console.print(f"[red]Error: jobs fetch failed (--refresh disables cache fallback): {e}[/red]")
            return None

    return headlines, jobs, fetch_status


def _run_pipeline(
    city: str,
    industry: str,
    out_dir: Path,
    jobs_limit: int,
    headlines_limit: int,
    jobs_provider: str,
    allow_provider_fallback: bool,
    write_leads: bool,
    refresh: bool,
    deterministic: bool,
    *,
    objective: str | None = None,
) -> int:
    """
    Core pipeline: fetch signals → generate v2.0 strategy → write artifacts → print summary.

    Artifacts written:
      input_signals.json, strategy.json, signal_analysis.json,
      report.md, report.html, summary.txt, [leads.csv]
    """
    # Validate inputs first — fast, no I/O, no Rich dependency.
    validated = _validate_and_normalize(city, industry)
    if validated is None:
        return 1
    city, industry = validated

    from marketscout.brain import generate_strategy, strategy_to_html, strategy_to_markdown
    from marketscout.brain.strategy import build_signal_analysis
    from marketscout.config import get_cache_dir, get_disk_cache_ttl_seconds, get_strategy_mode
    from marketscout.leads import build_leads

    try:
        from rich.console import Console
        from rich.table import Table
    except ImportError:
        print(f"MarketScout {__version__} requires 'rich'. Install with: pip install rich", file=sys.stderr)
        return 1

    console = Console()
    err_console = Console(file=sys.stderr)

    if refresh:
        err_console.print("[cyan]--refresh: requiring live fetch, cache fallback disabled.[/cyan]")

    started_at = datetime.now(timezone.utc)
    t0 = time.monotonic()

    result = _fetch_signals(
        city=city,
        industry=industry,
        headlines_limit=headlines_limit,
        jobs_limit=jobs_limit,
        jobs_provider=jobs_provider,
        allow_provider_fallback=allow_provider_fallback,
        refresh=refresh,
        cache_dir=get_cache_dir(),
        ttl=get_disk_cache_ttl_seconds(),
        err_console=err_console,
    )
    if result is None:
        return 1
    headlines, jobs, fetch_status = result

    strategy = generate_strategy(
        headlines,
        industry=industry,
        city=city,
        jobs=jobs,
        objective=objective,
        deterministic=deterministic,
    )

    duration_ms = int((time.monotonic() - t0) * 1000)
    cache_used = any(
        entry.get("status") == "cached"
        for entry in fetch_status.values()
    )
    run_id = str(uuid.uuid4())
    run_metadata = {
        "run_id": run_id,
        "started_at_iso": started_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "duration_ms": duration_ms,
        "deterministic": deterministic,
        "cache_used": cache_used,
    }

    out_dir = out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    input_signals_path = out_dir / "input_signals.json"
    strategy_path = out_dir / "strategy.json"
    signal_analysis_path = out_dir / "signal_analysis.json"
    report_md_path = out_dir / "report.md"
    report_html_path = out_dir / "report.html"
    summary_path = out_dir / "summary.txt"
    leads_path = out_dir / "leads.csv"

    input_signals_path.write_text(json.dumps({"headlines": headlines, "jobs": jobs}, indent=2), encoding="utf-8")
    strategy_path.write_text(json.dumps(strategy.to_json_dict(), indent=2), encoding="utf-8")

    signal_analysis = build_signal_analysis(
        headlines, jobs, city, industry,
        run_metadata=run_metadata,
        fetch_status=fetch_status,
        strategy_mode=get_strategy_mode(),
    )
    signal_analysis_path.write_text(json.dumps(signal_analysis, indent=2), encoding="utf-8")

    report_md_path.write_text(strategy_to_markdown(strategy.to_json_dict(), signal_analysis=signal_analysis), encoding="utf-8")
    report_html_path.write_text(strategy_to_html(strategy.to_json_dict(), signal_analysis=signal_analysis), encoding="utf-8")

    # summary.txt
    summary_lines: list[str] = [f"MarketScout — {city} | {industry}"]
    if objective:
        summary_lines.append(f"Objective (label): {objective}")
    su = getattr(strategy, "signals_used", None)
    if su:
        summary_lines.append(f"Signals — Headlines: {su.headlines_count}, Jobs: {su.jobs_count}")
    dq = getattr(strategy, "data_quality", None)
    if dq:
        summary_lines.append(
            f"Data quality — freshness: {dq.freshness_window_days}d, "
            f"coverage: {dq.coverage_score:.2f}, source mix: {dq.source_mix_score:.2f}"
        )
    opps = getattr(strategy, "opportunity_map", [])
    summary_lines.append(f"Opportunities: {len(opps)}")
    for o in opps[:5]:
        summary_lines.append(
            f"  - {getattr(o, 'title', '')[:50]} "
            f"(pain={getattr(o, 'pain_score', 0)}, roi={getattr(o, 'roi_signal', 0)})"
        )
    summary_path.write_text("\n".join(summary_lines) + "\n", encoding="utf-8")

    lead_rows: list[dict] | None = None
    if write_leads:
        leads = build_leads(jobs)
        lead_rows = [asdict(lead) for lead in leads]
        with leads_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["company", "job_count", "top_keywords", "readiness_score", "example_links"])
            writer.writeheader()
            for row in lead_rows:
                writer.writerow(row)

    # Persist run to SQLite (non-fatal — DB failures never break artifact generation)
    try:
        from marketscout.db import get_connection, save_run
        _db_conn = get_connection()
        try:
            save_run(
                conn=_db_conn,
                run_id=run_id,
                city=city,
                industry=industry,
                strategy=strategy,
                headlines=headlines,
                jobs=jobs,
                fetch_status=fetch_status,
                run_metadata=run_metadata,
                strategy_mode=get_strategy_mode(),
                leads=lead_rows,
            )
        finally:
            _db_conn.close()
    except Exception:
        pass  # DB errors are silently swallowed so artifacts are always delivered

    # Rich terminal output
    console.print(f"\n[bold]MarketScout v{__version__}[/bold]\n")

    fetch_table = Table(title="Fetch status")
    fetch_table.add_column("Source", style="cyan")
    fetch_table.add_column("Provider")
    fetch_table.add_column("Status")
    fetch_table.add_column("Note")
    _STATUS_STYLE = {"live": "green", "cached": "yellow", "failed": "red"}
    for source, entry in fetch_status.items():
        status = entry.get("status", "")
        style = _STATUS_STYLE.get(status, "")
        note = entry.get("error") or ""
        fetch_table.add_row(
            source,
            entry.get("provider", ""),
            f"[{style}]{status}[/{style}]" if style else status,
            note[:60],
        )
    console.print(fetch_table)
    console.print()

    if dq:
        dq_table = Table(title="Data quality")
        dq_table.add_column("Metric", style="cyan")
        dq_table.add_column("Value", justify="right")
        dq_table.add_row("Freshness window (days)", str(dq.freshness_window_days))
        dq_table.add_row("Coverage score", f"{dq.coverage_score:.2f}")
        dq_table.add_row("Source mix score", f"{dq.source_mix_score:.2f}")
        console.print(dq_table)
        console.print()

    opps = getattr(strategy, "opportunity_map", [])
    if opps:
        opp_table = Table(title="Top 5 opportunities")
        opp_table.add_column("Title", style="cyan", max_width=40)
        opp_table.add_column("Pain", justify="right")
        opp_table.add_column("ROI", justify="right")
        opp_table.add_column("Conf.", justify="right")
        opp_table.add_column("Category")
        for o in opps[:5]:
            opp_table.add_row(
                (getattr(o, "title", "") or "")[:40],
                str(getattr(o, "pain_score", 0)),
                str(getattr(o, "roi_signal", 0)),
                f"{getattr(o, 'confidence', 0):.2f}",
                (getattr(o, "ai_category", "") or "")[:20],
            )
        console.print(opp_table)

    console.print("\n[green]Outputs:[/green]")
    for p in [input_signals_path, strategy_path, signal_analysis_path, report_md_path, report_html_path, summary_path]:
        console.print(f"  {p}")
    if write_leads:
        console.print(f"  {leads_path}")
    console.print()
    return 0


def cmd_run(
    city: str,
    industry: str,
    out_dir: Path,
    jobs_limit: int,
    headlines_limit: int,
    jobs_provider: str,
    allow_provider_fallback: bool,
    write_leads: bool,
    refresh: bool,
    deterministic: bool,
    objective: str | None = None,
) -> int:
    """Run the pipeline with live signals and write v2.0 artifacts."""
    return _run_pipeline(
        city=city,
        industry=industry,
        out_dir=out_dir,
        jobs_limit=jobs_limit,
        headlines_limit=headlines_limit,
        jobs_provider=jobs_provider,
        allow_provider_fallback=allow_provider_fallback,
        write_leads=write_leads,
        refresh=refresh,
        deterministic=deterministic,
        objective=objective,
    )


# Required files for bundle (leads.csv and signal_analysis.json optional)
BUNDLE_REQUIRED = ("input_signals.json", "strategy.json", "report.html", "summary.txt")
BUNDLE_OPTIONAL = ("leads.csv", "signal_analysis.json")


def cmd_bundle(out_dir: Path | None) -> int:
    """
    Bundle a run directory: validate required files, copy into bundle/, create zip.
    Default out_dir is the latest run under ./out (by mtime).
    """
    if out_dir is None:
        out_dir = find_latest_run_dir(Path("out"))
        if out_dir is None:
            print("Error: no run directory found under out/. Pass --out-dir explicitly.", file=sys.stderr)
            return 1
    out_dir = Path(out_dir).resolve()
    if not out_dir.is_dir():
        print(f"Error: not a directory: {out_dir}", file=sys.stderr)
        return 1

    for name in BUNDLE_REQUIRED:
        if not (out_dir / name).is_file():
            print(f"Error: missing required file: {out_dir / name}", file=sys.stderr)
            return 1

    try:
        strategy_data = json.loads((out_dir / "strategy.json").read_text(encoding="utf-8"))
        city = (strategy_data.get("city") or "unknown").replace(" ", "_")[:30]
        industry = (strategy_data.get("industry") or "unknown").replace(" ", "_")[:30]
    except (OSError, json.JSONDecodeError, KeyError):
        city, industry = "unknown", "unknown"

    date_match = re.search(r"(\d{4}-\d{2}-\d{2})$", out_dir.name)
    date_str = date_match.group(1) if date_match else datetime.now().strftime("%Y-%m-%d")
    zip_name = f"marketscout_{city}_{industry}_{date_str}.zip"
    zip_path = out_dir / zip_name

    bundle_dir = out_dir / "bundle"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    for name in BUNDLE_REQUIRED:
        shutil.copy2(out_dir / name, bundle_dir / name)
    for name in BUNDLE_OPTIONAL:
        p = out_dir / name
        if p.is_file():
            shutil.copy2(p, bundle_dir / name)

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in bundle_dir.iterdir():
            if f.is_file():
                zf.write(f, f.name)

    print(zip_path)
    return 0


def cmd_eval(signals_path: Path, strategy_path: Path, out_path: Path | None) -> int:
    """
    Quality gate: validate v2.0 strategy and evidence links; write eval_report.md.
    Exit 0 if all checks pass, 1 otherwise.
    """
    from marketscout.brain.schema import StrategyOutput

    if out_path is None:
        out_path = strategy_path.parent / "eval_report.md"
    out_path = Path(out_path).resolve()

    results: list[tuple[str, bool, str]] = []

    try:
        signals_data = json.loads(signals_path.read_text(encoding="utf-8"))
        headlines = signals_data.get("headlines") or []
        jobs = signals_data.get("jobs") or []
    except (OSError, json.JSONDecodeError) as e:
        results.append(("signals_load", False, str(e)))
        _write_eval_report(out_path, results, None)
        return 1

    allowed_links: set[str] = set()
    for h in headlines:
        link = (h.get("link") or "").strip()
        if link:
            allowed_links.add(link)
    for j in jobs:
        link = (j.get("link") or "").strip()
        if link:
            allowed_links.add(link)
    # Note: "#" is NOT added unconditionally — it is only valid if a signal itself has "#" as its link.

    try:
        strategy_raw = json.loads(strategy_path.read_text(encoding="utf-8"))
        strategy = StrategyOutput.model_validate(strategy_raw)
    except (OSError, json.JSONDecodeError, Exception) as e:
        results.append(("v2_schema", False, str(e)))
        _write_eval_report(out_path, results, None)
        return 1
    results.append(("v2_schema", True, "Strategy validates v2.0 schema"))

    n_opp = len(strategy.opportunity_map)
    results.append(("opportunity_map_length", 5 <= n_opp <= 8, f"opportunity_map length {n_opp} in [5,8]"))

    scores_ok = all(
        0 <= o.confidence <= 1
        and 0 <= o.pain_score <= 10
        and 0 <= o.automation_potential <= 10
        and 0 <= o.roi_signal <= 10
        for o in strategy.opportunity_map
    )
    results.append(("scores_bounds", scores_ok, "Each opportunity: confidence in [0,1], pain/automation/roi in [0,10]"))

    # signals_used counts must match what is actually present in input_signals.json
    expected_h = len(headlines)
    expected_j = len(jobs)
    actual_h = strategy.signals_used.headlines_count
    actual_j = strategy.signals_used.jobs_count
    signals_count_ok = (actual_h == expected_h) and (actual_j == expected_j)
    results.append((
        "signals_used_counts",
        signals_count_ok,
        f"signals_used counts match input_signals.json "
        f"(headlines: expected {expected_h}, got {actual_h}; "
        f"jobs: expected {expected_j}, got {actual_j})",
    ))

    evidence_count_ok = all(len(o.evidence) >= 2 for o in strategy.opportunity_map)
    results.append(("evidence_count", evidence_count_ok, "Each opportunity has >= 2 evidence items"))

    bad_links: list[str] = [
        e.link
        for o in strategy.opportunity_map
        for e in o.evidence
        if e.link not in allowed_links
    ]
    links_ok = len(bad_links) == 0
    results.append((
        "evidence_links_in_signals",
        links_ok,
        "All evidence links present in input signals" + (f"; bad: {bad_links[:5]}" if bad_links else ""),
    ))

    dq = strategy.data_quality
    coverage_ok = 0 <= dq.coverage_score <= 1
    results.append(("data_quality_coverage", coverage_ok, f"data_quality.coverage_score={dq.coverage_score} in [0,1]"))

    score_breakdown_ok = all(
        abs(sb.signal_frequency + sb.source_diversity + sb.job_role_density - 1.0) <= 1e-6
        for o in strategy.opportunity_map
        if (sb := getattr(o, "score_breakdown", None)) is not None
    )
    results.append(("score_breakdown_sum", score_breakdown_ok, "Each score_breakdown (when present) sums to 1.0"))

    _write_eval_report(out_path, results, strategy)
    return 0 if all(r[1] for r in results) else 1


def _write_eval_report(out_path: Path, results: list[tuple[str, bool, str]], strategy) -> None:
    """Write eval_report.md from (check_id, passed, message) results."""
    lines = ["# Eval Report", "", "| Check | Pass | Message |", "|-------|------|--------|"]
    for check_id, passed, msg in results:
        lines.append(f"| {check_id} | {'pass' if passed else 'fail'} | {msg.replace('|', chr(124))[:80]} |")
    lines.append("")
    passed_count = sum(1 for _, p, _ in results if p)
    lines.append(f"**Result:** {passed_count}/{len(results)} checks passed.")
    lines.append("")
    if strategy:
        lines.append(f"- City: {strategy.city}, Industry: {strategy.industry}")
        lines.append(f"- Opportunities: {len(strategy.opportunity_map)}")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")


def cmd_opp_list(
    status: str | None = None,
    city: str | None = None,
    industry: str | None = None,
    limit: int = 20,
) -> int:
    """List stored opportunities with their workflow status."""
    try:
        from rich.console import Console
        from rich.table import Table
    except ImportError:
        print(f"MarketScout {__version__} requires 'rich'. Install with: pip install rich", file=sys.stderr)
        return 1

    try:
        from marketscout.db import get_connection, list_opportunities
        conn = get_connection()
        rows = list_opportunities(conn, city=city, industry=industry, status=status, limit=limit)
        conn.close()
    except Exception as e:
        print(f"Error: could not read opportunities: {e}", file=sys.stderr)
        return 1

    console = Console()
    if not rows:
        console.print("[yellow]No opportunities found.[/yellow]")
        return 0

    _STATUS_STYLE = {
        "discovered": "white",
        "under_review": "yellow",
        "prioritized": "bold green",
        "rejected": "red",
        "pursued": "bold cyan",
    }
    table = Table(title="Opportunities")
    table.add_column("ID", style="dim", justify="right")
    table.add_column("Title", style="cyan", max_width=40)
    table.add_column("City")
    table.add_column("Industry")
    table.add_column("Pain", justify="right")
    table.add_column("ROI", justify="right")
    table.add_column("Status")
    table.add_column("Run date")
    for r in rows:
        st = r["status"] or "discovered"
        style = _STATUS_STYLE.get(st, "white")
        table.add_row(
            str(r["id"]),
            (r["title"] or "")[:40],
            r["city"] or "",
            r["industry"] or "",
            f"{r['pain_score']:.1f}" if r["pain_score"] is not None else "",
            f"{r['roi_signal']:.1f}" if r["roi_signal"] is not None else "",
            f"[{style}]{st}[/{style}]",
            (r["created_at"] or "")[:10],
        )
    console.print(table)
    return 0


def cmd_opp_set(opp_id: int, status: str, note: str | None = None) -> int:
    """Transition an opportunity's workflow status."""
    try:
        from marketscout.db import VALID_STATUSES, get_connection, update_opportunity_status
        if status not in VALID_STATUSES:
            print(
                f"Error: invalid status '{status}'. Valid: {', '.join(VALID_STATUSES)}",
                file=sys.stderr,
            )
            return 1
        conn = get_connection()
        found = update_opportunity_status(conn, opp_id, status, note)
        conn.close()
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    if not found:
        print(f"Error: no opportunity with id {opp_id}.", file=sys.stderr)
        return 1
    suffix = f" — {note}" if note else ""
    print(f"Opportunity {opp_id} → {status}{suffix}")
    return 0


def cmd_history(limit: int = 10) -> int:
    """Print recent runs as a Rich table. Returns 0 on success, 1 on error."""
    try:
        from rich.console import Console
        from rich.table import Table
    except ImportError:
        print(f"MarketScout {__version__} requires 'rich'. Install with: pip install rich", file=sys.stderr)
        return 1

    try:
        from marketscout.db import get_connection, list_runs
        conn = get_connection()
        rows = list_runs(conn, limit=limit)
        conn.close()
    except Exception as e:
        print(f"Error: could not read run history: {e}", file=sys.stderr)
        return 1

    console = Console()
    if not rows:
        console.print("[yellow]No runs found in database.[/yellow]")
        return 0

    table = Table(title=f"Run history (last {limit})")
    table.add_column("Run ID", style="dim", max_width=12)
    table.add_column("Created at")
    table.add_column("City", style="cyan")
    table.add_column("Industry", style="cyan")
    table.add_column("Mode")
    table.add_column("Headlines", justify="right")
    table.add_column("Jobs", justify="right")
    table.add_column("Coverage", justify="right")

    for r in rows:
        run_id_short = (r["run_id"] or "")[:8]
        table.add_row(
            run_id_short,
            r["created_at"] or "",
            r["city"] or "",
            r["industry"] or "",
            r["strategy_mode"] or "",
            str(r["headlines_count"] or 0),
            str(r["jobs_count"] or 0),
            f"{r['coverage_score']:.2f}" if r["coverage_score"] is not None else "",
        )

    console.print(table)
    return 0


def cmd_compare(city: str, industry: str, limit_runs: int = 3) -> int:
    """
    Compare the last N runs for a city + industry, aggregating opportunity scores.
    Returns 0 on success, 1 on error.
    """
    try:
        from rich.console import Console
        from rich.table import Table
    except ImportError:
        print(f"MarketScout {__version__} requires 'rich'. Install with: pip install rich", file=sys.stderr)
        return 1

    try:
        from marketscout.db import compare_runs, get_connection, get_trend_data
        conn = get_connection()
        run_rows, opp_rows = compare_runs(conn, city=city, industry=industry, limit_runs=limit_runs)
        trend_rows = get_trend_data(conn, city=city, industry=industry, limit_runs=limit_runs)
        conn.close()
    except Exception as e:
        print(f"Error: could not read comparison data: {e}", file=sys.stderr)
        return 1

    console = Console()

    if not run_rows:
        console.print(f"[yellow]No runs found for city='{city}', industry='{industry}'.[/yellow]")
        return 0

    run_table = Table(title=f"Recent runs — {city} / {industry}")
    run_table.add_column("Run ID", style="dim", max_width=12)
    run_table.add_column("Created at")
    run_table.add_column("Mode")
    run_table.add_column("Headlines", justify="right")
    run_table.add_column("Jobs", justify="right")
    for r in run_rows:
        run_table.add_row(
            (r["run_id"] or "")[:8],
            r["created_at"] or "",
            r["strategy_mode"] or "",
            str(r["headlines_count"] or 0),
            str(r["jobs_count"] or 0),
        )
    console.print(run_table)
    console.print()

    if opp_rows:
        opp_table = Table(title="Aggregated opportunities (across runs)")
        opp_table.add_column("Title", style="cyan", max_width=45)
        opp_table.add_column("Avg pain", justify="right")
        opp_table.add_column("Avg ROI", justify="right")
        opp_table.add_column("Avg conf.", justify="right")
        opp_table.add_column("Appearances", justify="right")
        for o in opp_rows:
            opp_table.add_row(
                (o["title"] or "")[:45],
                f"{o['avg_pain']:.2f}" if o["avg_pain"] is not None else "",
                f"{o['avg_roi']:.2f}" if o["avg_roi"] is not None else "",
                f"{o['avg_confidence']:.2f}" if o["avg_confidence"] is not None else "",
                str(o["appearances"] or 0),
            )
        console.print(opp_table)
        console.print()

    if trend_rows:
        _TREND_LABEL = {
            "rising":  "[bold green]↑ rising[/bold green]",
            "stable":  "[white]→ stable[/white]",
            "falling": "[red]↓ falling[/red]",
            "single":  "[dim]· single[/dim]",
        }
        _PERSIST_LABEL = {
            True:  "[bold green]persistent[/bold green]",
            False: "[yellow]recurring[/yellow]",
        }
        trend_table = Table(title="Signal trends")
        trend_table.add_column("Title", style="cyan", max_width=45)
        trend_table.add_column("Appearances", justify="right")
        trend_table.add_column("Avg pain", justify="right")
        trend_table.add_column("Trend")
        trend_table.add_column("Strength")
        for t in trend_rows:
            appearances = t["appearances"]
            is_persistent = appearances >= limit_runs
            strength = _PERSIST_LABEL[is_persistent] if appearances > 1 else "[dim]one-time[/dim]"
            trend_table.add_row(
                (t["title"] or "")[:45],
                str(appearances),
                f"{t['avg_pain']:.2f}",
                _TREND_LABEL.get(t["trend"], t["trend"]),
                strength,
            )
        console.print(trend_table)

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="marketscout",
        description=(
            "MarketScout — AI opportunity mapping from live market signals.\n"
            "Commands: run (fetch + generate), eval (quality gate), bundle (package for sharing)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=False)

    # ── run ───────────────────────────────────────────────────────────────────
    p_run = subparsers.add_parser(
        "run",
        help="Fetch market signals and generate a v2.0 opportunity map.",
        description=(
            "Fetch live headlines and job postings for a city + industry, generate a scored\n"
            "opportunity map, and write all artifacts to the output directory."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_run.add_argument(
        "--city",
        type=str,
        required=True,
        metavar="CITY",
        help="Target city (required). Accepts postal suffixes, e.g. 'Vancouver, BC'.",
    )
    p_run.add_argument(
        "--industry",
        type=str,
        required=True,
        metavar="INDUSTRY",
        help=(
            "Target industry (required). Case-insensitive; common aliases accepted "
            "(e.g. 'tech' → Technology). Run with an unknown value to see the supported list."
        ),
    )
    p_run.add_argument(
        "-o", "--out-dir",
        type=Path,
        default=None,
        metavar="DIR",
        help="Output directory (default: out/<city>_<industry>_<date>/).",
    )
    p_run.add_argument(
        "--jobs-provider",
        type=str,
        default="adzuna",
        choices=["adzuna", "rss"],
        help="Jobs data source: 'adzuna' (default) or 'rss'.",
    )
    p_run.add_argument(
        "--jobs-limit",
        type=int,
        default=10,
        metavar="N",
        help="Maximum number of job postings to fetch (default: 10).",
    )
    p_run.add_argument(
        "--headlines-limit",
        type=int,
        default=10,
        metavar="N",
        help="Maximum number of news headlines to fetch (default: 10).",
    )
    p_run.add_argument(
        "--refresh",
        action="store_true",
        help=(
            "Require a fresh live fetch. Disables cache fallback — "
            "exits non-zero if the network is unavailable."
        ),
    )
    p_run.add_argument(
        "--deterministic",
        action="store_true",
        help=(
            "Produce reproducible outputs: seed random at 42, sort signals by title, "
            "use stable opportunity ordering."
        ),
    )
    p_run.add_argument(
        "--objective",
        type=str,
        default=None,
        metavar="TEXT",
        help="Optional free-text label for this run (not used in scoring or output).",
    )
    p_run.add_argument(
        "--allow-provider-fallback",
        action="store_true",
        help="Fall back to the RSS jobs provider if the primary provider (Adzuna) fails.",
    )
    p_run.add_argument(
        "--write-leads",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Write leads.csv from job data (default: enabled). Use --no-write-leads to skip.",
    )
    p_run.set_defaults(
        func=lambda ns: cmd_run(
            city=ns.city,
            industry=ns.industry,
            out_dir=ns.out_dir or _default_out_dir(ns.city, ns.industry),
            jobs_limit=ns.jobs_limit,
            headlines_limit=ns.headlines_limit,
            jobs_provider=ns.jobs_provider,
            allow_provider_fallback=ns.allow_provider_fallback,
            write_leads=ns.write_leads,
            refresh=ns.refresh,
            deterministic=ns.deterministic,
            objective=ns.objective,
        )
    )

    # ── bundle ────────────────────────────────────────────────────────────────
    p_bundle = subparsers.add_parser(
        "bundle",
        help="Validate and pack a run directory into a shareable zip.",
        description=(
            "Verify that all required run artifacts are present, copy them into a bundle/\n"
            "subdirectory, and create a zip archive inside the run directory."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_bundle.add_argument(
        "-o", "--out-dir",
        type=Path,
        default=None,
        metavar="DIR",
        help="Path to an existing run directory (default: latest run under out/ by mtime).",
    )
    p_bundle.set_defaults(func=lambda ns: cmd_bundle(ns.out_dir))

    # ── eval ──────────────────────────────────────────────────────────────────
    p_eval = subparsers.add_parser(
        "eval",
        help="Quality gate: verify schema, scores, evidence count, and source integrity.",
        description=(
            "Validate a v2.0 strategy against input signals. Checks:\n"
            "  • strategy.json matches the v2.0 schema\n"
            "  • opportunity_map length in [5, 8]\n"
            "  • confidence in [0,1] and pain/automation/roi scores in [0,10]\n"
            "  • each opportunity has >= 2 evidence items\n"
            "  • every evidence.link exists in input_signals.json (no hallucinated sources)\n"
            "  • data_quality.coverage_score in [0,1]\n\n"
            "Writes eval_report.md. Exits 0 if all checks pass, 1 otherwise."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_eval.add_argument(
        "--signals",
        type=Path,
        required=True,
        metavar="FILE",
        help="Path to input_signals.json produced by 'run'.",
    )
    p_eval.add_argument(
        "--strategy",
        type=Path,
        required=True,
        metavar="FILE",
        help="Path to strategy.json produced by 'run'.",
    )
    p_eval.add_argument(
        "--out",
        type=Path,
        default=None,
        metavar="FILE",
        help="Where to write eval_report.md (default: next to strategy.json).",
    )
    p_eval.set_defaults(func=lambda ns: cmd_eval(ns.signals, ns.strategy, ns.out))

    # ── opp ───────────────────────────────────────────────────────────────────
    p_opp = subparsers.add_parser(
        "opp",
        help="Manage individual opportunities (list, update workflow status).",
        description="View and manage stored opportunities and their decision workflow status.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    opp_subs = p_opp.add_subparsers(dest="opp_command", required=True)

    # opp list
    p_opp_list = opp_subs.add_parser(
        "list",
        help="List stored opportunities with workflow status.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_opp_list.add_argument("--status", type=str, default=None,
        metavar="STATUS",
        help=f"Filter by status. One of: {', '.join(['discovered', 'under_review', 'prioritized', 'rejected', 'pursued'])}.")
    p_opp_list.add_argument("--city", type=str, default=None, metavar="CITY",
        help="Filter by city.")
    p_opp_list.add_argument("--industry", type=str, default=None, metavar="INDUSTRY",
        help="Filter by industry.")
    p_opp_list.add_argument("--limit", type=int, default=20, metavar="N",
        help="Maximum number of opportunities to show (default: 20).")
    p_opp_list.set_defaults(
        func=lambda ns: cmd_opp_list(ns.status, ns.city, ns.industry, ns.limit)
    )

    # opp set
    p_opp_set = opp_subs.add_parser(
        "set",
        help="Update the workflow status of an opportunity.",
        description=(
            "Transition an opportunity's status.\n"
            "Valid statuses: discovered → under_review → prioritized → pursued\n"
            "                                            ↘ rejected"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_opp_set.add_argument("opp_id", type=int, metavar="ID",
        help="Opportunity ID (from 'opp list').")
    p_opp_set.add_argument("--status", type=str, required=True,
        choices=["discovered", "under_review", "prioritized", "rejected", "pursued"],
        help="New workflow status.")
    p_opp_set.add_argument("--note", type=str, default=None, metavar="TEXT",
        help="Optional annotation stored in the workflow audit log.")
    p_opp_set.set_defaults(
        func=lambda ns: cmd_opp_set(ns.opp_id, ns.status, ns.note)
    )

    # ── history ───────────────────────────────────────────────────────────────
    p_history = subparsers.add_parser(
        "history",
        help="Show recent runs stored in the SQLite database.",
        description="Print a table of the most recent MarketScout runs from the local database.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_history.add_argument(
        "--limit",
        type=int,
        default=10,
        metavar="N",
        help="Number of recent runs to show (default: 10).",
    )
    p_history.set_defaults(func=lambda ns: cmd_history(ns.limit))

    # ── compare ───────────────────────────────────────────────────────────────
    p_compare = subparsers.add_parser(
        "compare",
        help="Compare the last N runs for a city + industry, aggregating opportunity scores.",
        description=(
            "Show the most recent runs for a city/industry pair and aggregate\n"
            "opportunity scores across them to surface consistently high-scoring opportunities."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_compare.add_argument(
        "--city",
        type=str,
        required=True,
        metavar="CITY",
        help="Target city to compare runs for.",
    )
    p_compare.add_argument(
        "--industry",
        type=str,
        required=True,
        metavar="INDUSTRY",
        help="Target industry to compare runs for.",
    )
    p_compare.add_argument(
        "--limit-runs",
        type=int,
        default=3,
        metavar="N",
        help="Number of most recent runs to aggregate (default: 3).",
    )
    p_compare.set_defaults(func=lambda ns: cmd_compare(ns.city, ns.industry, ns.limit_runs))

    # ── menu ──────────────────────────────────────────────────────────────────
    p_menu = subparsers.add_parser(
        "menu",
        help="Launch interactive mode (guided terminal menu).",
        description="Start the interactive menu. Equivalent to running marketscout with no arguments.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_menu.set_defaults(func=lambda ns: _launch_interactive())

    args = parser.parse_args()

    # No subcommand given — launch interactive mode
    if not hasattr(args, "func"):
        return _launch_interactive()

    return args.func(args)


def _launch_interactive() -> int:
    """Lazy import and launch of interactive mode (avoids circular import at module level)."""
    from marketscout.interactive import run_menu
    return run_menu()


if __name__ == "__main__":
    sys.exit(main())
