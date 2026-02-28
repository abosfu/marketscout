"""Convert strategy JSON to human-readable Markdown report. Never crashes; validates first."""

from __future__ import annotations

from typing import Any

from marketscout.brain.schema import StrategyOutput


def strategy_to_markdown(data: dict[str, Any] | StrategyOutput) -> str:
    """
    Convert strategy to Markdown. Accepts dict or StrategyOutput.
    Validates first; on validation failure returns a minimal safe report.
    Missing fields are skipped or replaced with placeholders so the function never raises.
    """
    try:
        if isinstance(data, StrategyOutput):
            strategy = data
        else:
            strategy = StrategyOutput.model_validate(data)
    except Exception:
        return "# Strategy Report\n\nUnable to validate strategy data. Please check the input.\n"

    sections: list[str] = []

    # Executive Summary
    pain = getattr(strategy, "pain_score", 0)
    n_problems = len(getattr(strategy, "problems", []))
    sections.append("# Executive Summary\n")
    sections.append(
        f"This strategy report has a **Pain Score** of {pain}/10 "
        f"and identifies {n_problems} opportunity areas with evidence from recent headlines and job signals.\n"
    )

    # Signals Used
    signals = getattr(strategy, "signals_used", None)
    if signals is not None:
        sections.append("# Signals Used\n")
        sections.append(f"- **Headlines count:** {getattr(signals, 'headlines_count', 0)}\n")
        sections.append(f"- **Jobs count:** {getattr(signals, 'jobs_count', 0)}\n")
        sections.append(f"- **Econ used:** {getattr(signals, 'econ_used', False)}\n")

    # Score Breakdown
    breakdown = getattr(strategy, "score_breakdown", None)
    if breakdown is not None:
        sections.append("# Score Breakdown\n")
        sections.append(f"- **News signal score (0-10):** {getattr(breakdown, 'news_signal_score', 0)}\n")
        sections.append(f"- **Jobs signal score (0-10):** {getattr(breakdown, 'jobs_signal_score', 0)}\n")
        sections.append(f"- **Combined pain score (1-10):** {getattr(breakdown, 'combined_pain_score', 0)}\n")
        weights = getattr(breakdown, "weights", {}) or {}
        sections.append(f"- **Weights:** {weights}\n")

    # Opportunity Map (table)
    sections.append("# Opportunity Map\n")
    problems = getattr(strategy, "problems", [])
    if problems:
        sections.append("| Problem | Evidence | Link |")
        sections.append("|---------|----------|------|")
        for p in problems:
            prob = getattr(p, "problem", "")
            head = (getattr(p, "evidence_headline", "") or "")[:80]
            if len(getattr(p, "evidence_headline", "") or "") > 80:
                head += "..."
            link = getattr(p, "evidence_link", "") or "#"
            sections.append(f"| {prob} | {head} | {link} |")
        sections.append("")
    else:
        sections.append("*No problems documented.*\n")

    # AI Matches
    sections.append("# AI Matches\n")
    matches = getattr(strategy, "ai_matches", [])
    for m in matches:
        cat = getattr(m, "category", "Category")
        approach = getattr(m, "recommended_approach", "")
        sections.append(f"## {cat}\n\n{approach}\n")
    if not matches:
        sections.append("*No AI matches.*\n")

    # 30/60/90 Plan
    sections.append("# 30/60/90 Plan\n")
    plan = getattr(strategy, "plan_30_60_90", [])
    for phase in plan:
        ph = getattr(phase, "phase", "Phase")
        actions = getattr(phase, "actions", [])
        sections.append(f"## {ph}\n\n")
        for a in actions:
            sections.append(f"- {a}\n")
        sections.append("")
    if not plan:
        sections.append("*No plan phases.*\n")

    # ROI Notes & Assumptions
    sections.append("# ROI Notes & Assumptions\n")
    roi = getattr(strategy, "roi_notes", None)
    if roi:
        ranges = getattr(roi, "ranges", "") or ""
        assumptions = getattr(roi, "assumptions", []) or []
        sections.append(f"**Ranges:** {ranges}\n\n**Assumptions:**\n")
        for a in assumptions:
            sections.append(f"- {a}\n")
        sections.append("")
    else:
        sections.append("*No ROI notes.*\n")

    # Sources (links)
    sections.append("# Sources\n")
    seen_links: set[str] = set()
    for p in problems:
        link = getattr(p, "evidence_link", "") or ""
        if link and link != "#" and link not in seen_links:
            seen_links.add(link)
            head = getattr(p, "evidence_headline", "") or link
            sections.append(f"- [{head[:60]}]({link})\n")
    if not seen_links:
        sections.append("*No sources.*\n")

    return "\n".join(sections)
