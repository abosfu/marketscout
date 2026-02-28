"""CLI entrypoint: python -m marketscout run | scout | generate | demo."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from marketscout import __version__


def _data_dir() -> Path:
    return Path(__file__).resolve().parent.parent.parent / "data"


def _run(
    industry: str,
    objective: str,
    city: str,
    location: str,
    out_dir: Path,
    jobs_limit: int,
) -> int:
    """Fetch live signals, generate strategy, write strategy.json + report.md + report.html, print rich summary."""
    from marketscout.brain import generate_strategy, strategy_to_html, strategy_to_markdown
    from marketscout.cache import cache_key, read_cached, write_cached
    from marketscout.config import get_cache_dir, get_disk_cache_ttl_seconds, get_max_headlines
    from marketscout.scout import ScoutError, fetch_headlines, fetch_jobs

    try:
        from rich.console import Console
        from rich.table import Table
    except ImportError:
        print("MarketScout v1.1 requires 'rich'. Install with: pip install rich", file=sys.stderr)
        return 1

    console = Console()
    err_console = Console(file=sys.stderr)
    cache_dir = get_cache_dir()
    ttl = get_disk_cache_ttl_seconds()
    key = cache_key(city, industry)

    # --- Fetch headlines (live or cache on failure) ---
    headlines: list = []
    try:
        headlines = fetch_headlines(city=city, industry=industry, limit=get_max_headlines())
        write_cached(cache_dir, key, "headlines.json", headlines)
    except ScoutError as e:
        cached = read_cached(cache_dir, key, "headlines.json", ttl)
        if cached is not None and isinstance(cached, list):
            headlines = cached
            err_console.print("[yellow]Live fetch failed; using cached headlines.[/yellow]")
        else:
            err_console.print(f"[red]Headlines: {e}[/red]")
            return 1

    # --- Fetch jobs (live or cache on failure) ---
    jobs: list = []
    try:
        jobs = fetch_jobs(city=city, industry=industry, limit=jobs_limit)
        write_cached(cache_dir, key, "jobs.json", jobs)
    except ScoutError as e:
        cached = read_cached(cache_dir, key, "jobs.json", ttl)
        if cached is not None and isinstance(cached, list):
            jobs = cached
            err_console.print("[yellow]Live fetch failed; using cached jobs.[/yellow]")
        else:
            err_console.print(f"[red]Jobs: {e}[/red]")
            return 1

    # --- Generate strategy ---
    strategy = generate_strategy(
        headlines,
        industry=industry,
        objective=objective,
        location=location,
        jobs=jobs,
    )

    # --- Write outputs ---
    out_dir = out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    strategy_path = out_dir / "strategy.json"
    report_md_path = out_dir / "report.md"
    report_html_path = out_dir / "report.html"
    strategy_path.write_text(json.dumps(strategy.to_json_dict(), indent=2), encoding="utf-8")
    report_md_path.write_text(strategy_to_markdown(strategy.to_json_dict()), encoding="utf-8")
    report_html_path.write_text(strategy_to_html(strategy.to_json_dict()), encoding="utf-8")

    # --- Rich terminal summary ---
    console.print("\n[bold]MarketScout v1.1[/bold]\n")
    if strategy.signals_used:
        console.print("[bold]Signals used[/bold]")
        console.print(f"  Headlines: {strategy.signals_used.headlines_count}")
        console.print(f"  Jobs: {strategy.signals_used.jobs_count}\n")
    if strategy.score_breakdown:
        st = strategy.score_breakdown
        table = Table(title="Score breakdown")
        table.add_column("Signal", style="cyan")
        table.add_column("Score (0-10)", justify="right")
        table.add_row("News (headlines)", str(st.news_signal_score))
        table.add_row("Jobs", str(st.jobs_signal_score))
        table.add_row("Combined pain score", str(st.combined_pain_score))
        console.print(table)
        console.print()
    opp = Table(title="Opportunity map")
    opp.add_column("Problem", style="cyan")
    opp.add_column("Evidence", max_width=50)
    opp.add_column("Source")
    for p in strategy.problems:
        src = getattr(p, "evidence_source", "") or "—"
        opp.add_row(p.problem, (p.evidence_headline[:48] + "…") if len(p.evidence_headline) > 50 else p.evidence_headline, src)
    console.print(opp)
    console.print(f"\n[green]Outputs written to:[/green]")
    console.print(f"  {strategy_path}")
    console.print(f"  {report_md_path}")
    console.print(f"  {report_html_path}\n")
    return 0


def cmd_run(
    industry: str,
    objective: str,
    city: str,
    location: str,
    out_dir: Path,
    jobs_limit: int,
) -> int:
    """Main entry: run with live signals and write artifacts."""
    return _run(industry, objective, city, location, out_dir, jobs_limit)


def cmd_scout(
    output_path: Path | None = None,
    limit: int = 10,
    city: str | None = None,
    industry: str | None = None,
    include_jobs: bool = False,
    jobs_limit: int = 10,
) -> int:
    """Fetch headlines and optionally jobs (live); print/save as JSON. Exits non-zero on fetch failure."""
    from marketscout.scout import ScoutError, fetch_headlines, fetch_jobs

    try:
        headlines = fetch_headlines(limit=limit, city=city, industry=industry)
    except ScoutError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    if include_jobs:
        try:
            jobs = fetch_jobs(city=city, industry=industry, limit=jobs_limit)
        except ScoutError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1
        payload = {"headlines": headlines, "jobs": jobs}
    else:
        payload = headlines
    out = json.dumps(payload, indent=2)
    print(out)
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(out, encoding="utf-8")
        print(f"Saved to {output_path}", file=sys.stderr)
    return 0


def cmd_generate(
    headlines_path: Path | None = None,
    output_path: Path | None = None,
    industry: str = "Construction",
    objective: str = "Market entry",
    location: str = "Vancouver, BC",
) -> int:
    """Load headlines (+ jobs) JSON from file and write strategy JSON. For offline use with pre-fetched data."""
    from marketscout.brain import generate_strategy

    data_dir = _data_dir()
    if headlines_path is None:
        headlines_path = data_dir / "headlines.json"
    if not headlines_path.exists():
        print(f"Error: input file not found: {headlines_path}", file=sys.stderr)
        return 1
    try:
        raw = json.loads(headlines_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    if isinstance(raw, dict):
        headlines = raw.get("headlines") or []
        jobs = raw.get("jobs") or []
    else:
        headlines = raw if isinstance(raw, list) else []
        jobs = []
    if output_path is None:
        output_path = data_dir / "strategy.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    strategy = generate_strategy(headlines, industry=industry, objective=objective, location=location, jobs=jobs)
    output_path.write_text(json.dumps(strategy.to_json_dict(), indent=2), encoding="utf-8")
    print(json.dumps(strategy.to_json_dict(), indent=2))
    print(f"Saved to {output_path}", file=sys.stderr)
    return 0


def cmd_demo(data_dir: Path) -> int:
    """[Dev-only] Write demo_input.json and demo_strategy.json from data/sample_* (no network). For tests/fixtures."""
    from marketscout.brain import generate_strategy

    headlines_path = data_dir / "sample_headlines.json"
    jobs_path = data_dir / "sample_jobs.json"
    headlines: list = []
    jobs: list = []
    if headlines_path.exists():
        try:
            headlines = json.loads(headlines_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    if jobs_path.exists():
        try:
            jobs = json.loads(jobs_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    data_dir.mkdir(parents=True, exist_ok=True)
    demo_input_path = data_dir / "demo_input.json"
    demo_strategy_path = data_dir / "demo_strategy.json"
    demo_input = {"headlines": headlines, "jobs": jobs}
    demo_input_path.write_text(json.dumps(demo_input, indent=2), encoding="utf-8")
    print(f"Wrote {demo_input_path}", file=sys.stderr)
    strategy = generate_strategy(
        headlines,
        industry="Construction",
        objective="Market entry",
        location="Vancouver, BC",
        jobs=jobs,
        force_mock=True,
    )
    demo_strategy_path.write_text(json.dumps(strategy.to_json_dict(), indent=2), encoding="utf-8")
    print(f"Wrote {demo_strategy_path}", file=sys.stderr)
    print(json.dumps(strategy.to_json_dict(), indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="marketscout", description="MarketScout — Zero-Friction Strategy Engine (CLI)")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # run (primary)
    p_run = subparsers.add_parser("run", help="Fetch live signals, generate strategy, write strategy.json + report.md + report.html")
    p_run.add_argument("--industry", type=str, default="Construction", help="Industry")
    p_run.add_argument("--objective", type=str, default="Market entry", help="Objective")
    p_run.add_argument("--city", type=str, default="Vancouver", help="City for RSS")
    p_run.add_argument("--location", type=str, default="Vancouver, BC", help="Location label")
    p_run.add_argument("-o", "--out-dir", type=Path, default=Path("out"), help="Output directory (default: out)")
    p_run.add_argument("--jobs-limit", type=int, default=10, help="Max jobs to fetch")
    p_run.set_defaults(
        func=lambda ns: cmd_run(
            ns.industry,
            ns.objective,
            ns.city,
            ns.location,
            ns.out_dir,
            ns.jobs_limit,
        )
    )

    # demo (dev-only)
    p_demo = subparsers.add_parser("demo", help="[Dev-only] Build demo_input.json + demo_strategy.json from data/sample_* (no network)")
    p_demo.add_argument("--data-dir", type=Path, default=None, help="Data directory (default: ./data)")
    p_demo.set_defaults(func=lambda ns: cmd_demo(ns.data_dir or _data_dir()))

    # scout
    p_scout = subparsers.add_parser("scout", help="Fetch live headlines (and optionally jobs); print or save JSON")
    p_scout.add_argument("-o", "--output", type=Path, default=None, help="Write output to file")
    p_scout.add_argument("-n", "--limit", type=int, default=10, help="Max headlines")
    p_scout.add_argument("--city", type=str, default=None)
    p_scout.add_argument("--industry", type=str, default=None)
    p_scout.add_argument("--include-jobs", action="store_true")
    p_scout.add_argument("--jobs-limit", type=int, default=10)
    p_scout.set_defaults(
        func=lambda ns: cmd_scout(ns.output, ns.limit, ns.city, ns.industry, ns.include_jobs, ns.jobs_limit)
    )

    # generate
    p_gen = subparsers.add_parser("generate", help="Generate strategy from existing headlines JSON (e.g. from scout -o)")
    p_gen.add_argument("-i", "--headlines", type=Path, default=None)
    p_gen.add_argument("-o", "--output", type=Path, default=None)
    p_gen.add_argument("--industry", type=str, default="Construction")
    p_gen.add_argument("--objective", type=str, default="Market entry")
    p_gen.add_argument("--location", type=str, default="Vancouver, BC")
    p_gen.set_defaults(
        func=lambda ns: cmd_generate(
            ns.headlines,
            ns.output,
            ns.industry,
            ns.objective,
            ns.location,
        )
    )

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
