"""Convert strategy JSON (v2.0) to human-readable Markdown report. Never crashes; validates first."""

from __future__ import annotations

from typing import Any

from marketscout.backend.schema import StrategyOutput


def strategy_to_markdown(
    data: dict[str, Any] | StrategyOutput,
    *,
    signal_analysis: dict[str, Any] | None = None,
) -> str:
    """
    Convert v2.0 strategy to Markdown. Accepts dict or StrategyOutput.
    Sections: Executive Summary, Signal Analysis (if provided), Opportunity Map table,
    per-opportunity detail (problem, evidence, business case, score breakdown), Leads, Sources.
    """
    try:
        if isinstance(data, StrategyOutput):
            strategy = data
        else:
            strategy = StrategyOutput.model_validate(data)
    except Exception:
        return "# Strategy Report\n\nUnable to validate strategy data. Please check the input.\n"

    sections: list[str] = []

    # Executive Summary (city, industry, data quality)
    city = getattr(strategy, "city", "")
    industry = getattr(strategy, "industry", "")
    dq = getattr(strategy, "data_quality", None)
    sections.append("# Executive Summary\n")
    sections.append(f"**City:** {city}  \n**Industry:** {industry}\n")
    if dq is not None:
        sections.append(
            f"**Data quality:** freshness {getattr(dq, 'freshness_window_days', 0)} days | "
            f"coverage {getattr(dq, 'coverage_score', 0):.2f} | source mix {getattr(dq, 'source_mix_score', 0):.2f}\n"
        )
    signals = getattr(strategy, "signals_used", None)
    if signals is not None:
        sections.append(
            f"**Signals:** {getattr(signals, 'headlines_count', 0)} headlines, "
            f"{getattr(signals, 'jobs_count', 0)} jobs, "
            f"{getattr(signals, 'news_sources_count', 0)} news sources, "
            f"{getattr(signals, 'job_companies_count', 0)} job companies.\n"
        )

    # Signal Analysis (counts, fetch status, run metadata, keyword hits)
    if signal_analysis:
        sections.append("# Signal Analysis\n")
        sig = signal_analysis.get("signals") or {}
        sections.append(
            f"- **Headlines:** {sig.get('headlines_count', 0)} | **Jobs:** {sig.get('jobs_count', 0)} | "
            f"**Unique news sources:** {sig.get('unique_news_sources', 0)} | **Unique companies:** {sig.get('unique_companies', 0)}\n"
        )

        fetch_status = signal_analysis.get("fetch_status") or {}
        if fetch_status:
            sections.append("**Fetch status:**\n")
            sections.append("| Source | Provider | Status | Note |")
            sections.append("|--------|----------|--------|------|")
            for source, entry in fetch_status.items():
                provider = entry.get("provider", "")
                status = entry.get("status", "")
                note = (entry.get("error") or "")[:80]
                sections.append(f"| {source} | {provider} | {status} | {note} |")
            sections.append("")

        run_meta = signal_analysis.get("run_metadata") or {}
        if run_meta:
            sections.append(
                f"**Run:** started {run_meta.get('started_at_iso', '')} | "
                f"{run_meta.get('duration_ms', 0)} ms | "
                f"deterministic={run_meta.get('deterministic', False)} | "
                f"cache_used={run_meta.get('cache_used', False)}\n"
            )

        keyword_hits = signal_analysis.get("keyword_hits") or {}
        if keyword_hits:
            sections.append("**Keyword hits (tag → count):**\n")
            for tag, count in sorted(keyword_hits.items()):
                sections.append(f"- {tag}: {count}\n")
        top_tags = signal_analysis.get("top_tags") or []
        if top_tags:
            sections.append("**Top bottleneck tags:** " + ", ".join(top_tags[:5]) + "\n")
        sections.append("")

    # Opportunity Map table (title, pain, ROI signal, confidence, support level, recommendation, type)
    opps = getattr(strategy, "opportunity_map", [])
    sections.append("# Opportunity Map\n")
    if opps:
        sections.append("| Title | Pain | ROI | Conf | Support | Recommendation | Type |")
        sections.append("|-------|------|-----|------|---------|----------------|------|")
        for o in opps:
            raw_title = getattr(o, "title", "") or ""
            title = raw_title[:40] + ("..." if len(raw_title) > 40 else "")
            pain = getattr(o, "pain_score", 0)
            roi = getattr(o, "roi_signal", 0)
            conf = getattr(o, "confidence", 0)
            support = getattr(o, "support_level", "moderate")
            recommendation = getattr(o, "recommendation", "monitor")
            opp_type = getattr(o, "opportunity_type", "operational")
            padded = getattr(o, "is_padded", False)
            padded_mark = " ⚠" if padded else ""
            sections.append(f"| {title}{padded_mark} | {pain} | {roi} | {conf:.2f} | {support} | {recommendation} | {opp_type} |")
        sections.append("")
        sections.append("_⚠ = template-padded opportunity (limited direct evidence)_\n")
    else:
        sections.append("*No opportunities.*\n")

    # Each opportunity detail (problem, signal quality, evidence, business case)
    for i, o in enumerate(opps, 1):
        title = getattr(o, "title", "") or f"Opportunity {i}"
        sections.append(f"## {i}. {title}\n")

        # Signal quality and identity header
        support = getattr(o, "support_level", "moderate")
        age_avg = getattr(o, "signal_age_days_avg", None)
        unique_src = getattr(o, "unique_sources_count", 0)
        is_padded = getattr(o, "is_padded", False)
        recommendation = getattr(o, "recommendation", "monitor")
        opp_type = getattr(o, "opportunity_type", "operational")
        trend_key = getattr(o, "trend_key", "") or ""
        age_str = f"{age_avg:.0f}d avg age" if age_avg is not None else "age unknown"
        sections.append(f"**Signal quality:** `{support.upper()}` | {age_str} | {unique_src} unique source(s)\n")
        sections.append(f"**Decision:** `{recommendation}` | type: `{opp_type}`" + (f" | key: `{trend_key}`" if trend_key else "") + "\n")
        if is_padded:
            sections.append(
                "> **Template-padded** — no direct keyword evidence found for this bottleneck. "
                "Treat as hypothesis only; do not act without additional validation.\n"
            )

        sections.append(f"**Problem:** {getattr(o, 'problem', '')}\n")
        evidence_list = getattr(o, "evidence", []) or []
        if evidence_list:
            sections.append("**Evidence:**\n")
            for e in evidence_list:
                tit = getattr(e, "title", "") or ""
                link = getattr(e, "link", "") or "#"
                src = getattr(e, "source", "")
                sections.append(f"- [{tit[:70]}]({link}) ({src})")
            sections.append("")
        bc = getattr(o, "business_case", None)
        if bc:
            sections.append(f"**Business case:** {getattr(bc, 'savings_range_annual', '')}\n")
            for a in getattr(bc, "assumptions", []) or []:
                sections.append(f"- {a}\n")
        sb = getattr(o, "score_breakdown", None)
        if sb is not None:
            sections.append(
                f"**Score breakdown:** signal_frequency={getattr(sb, 'signal_frequency', 0):.2f} | "
                f"source_diversity={getattr(sb, 'source_diversity', 0):.2f} | job_role_density={getattr(sb, 'job_role_density', 0):.2f}\n"
            )
        br = getattr(o, "brief", None)
        if br is not None:
            sections.append("**Brief:**\n")
            sections.append(f"- **Likely buyer:** {getattr(br, 'likely_buyer', '')}")
            sections.append(f"- **Pain theme:** {getattr(br, 'pain_theme', '')}")
            sections.append(f"- **Commercial angle:** {getattr(br, 'commercial_angle', '')}")
            sections.append(f"- **Suggested next step:** {getattr(br, 'suggested_next_step', '')}")
            sections.append(f"- **Why now:** {getattr(br, 'why_now', '')}\n")
        actions = getattr(o, "suggested_actions", []) or []
        if actions:
            sections.append("**Suggested actions:**\n")
            for act in actions:
                sections.append(f"- {act}")
            sections.append("")
        opp_leads = getattr(o, "leads", []) or []
        if opp_leads:
            sections.append("**Potential leads:**\n")
            for lead in opp_leads:
                company = getattr(lead, "company_name", "")
                reason = getattr(lead, "reason", "")
                sig_type = getattr(lead, "signal_type", "")
                sections.append(f"- **{company}** — {reason} (signal: {sig_type})")
            sections.append("")
        sections.append("")

    # Leads section summary
    sections.append("# Leads\n")
    sections.append("See **leads.csv** for company-level leads (top companies by readiness).\n")

    # Sources list (from opportunity evidence links)
    sections.append("# Sources\n")
    seen_links: set[str] = set()
    for o in opps:
        for e in getattr(o, "evidence", []) or []:
            link = getattr(e, "link", "") or ""
            if link and link != "#" and link not in seen_links:
                seen_links.add(link)
                tit = getattr(e, "title", "") or link
                sections.append(f"- [{tit[:60]}]({link})\n")
    if not seen_links:
        sections.append("*No sources.*\n")

    return "\n".join(sections)
