"""Convert strategy JSON (v2.0) to a clean HTML report. Same sections as Markdown; minimal inline styling."""

from __future__ import annotations

from typing import Any

from marketscout.brain.schema import StrategyOutput

_STYLE = """
body { font-family: system-ui, -apple-system, sans-serif; max-width: 800px; margin: 0 auto; padding: 1rem; color: #333; }
h1 { font-size: 1.5rem; border-bottom: 1px solid #ddd; padding-bottom: 0.25rem; }
h2 { font-size: 1.2rem; margin-top: 1.25rem; }
table { border-collapse: collapse; width: 100%; margin: 0.5rem 0; }
th, td { border: 1px solid #ddd; padding: 0.4rem 0.6rem; text-align: left; }
th { background: #f5f5f5; }
ul { margin: 0.25rem 0; padding-left: 1.25rem; }
a { color: #0066cc; }
"""


def strategy_to_html(
    data: dict[str, Any] | StrategyOutput,
    *,
    signal_analysis: dict[str, Any] | None = None,
) -> str:
    """
    Convert v2.0 strategy to HTML. Sections: Executive Summary, Signal Analysis (if provided),
    Opportunity Map table, per-opportunity detail (with score breakdown), Leads summary, Sources.
    """
    try:
        if isinstance(data, StrategyOutput):
            strategy = data
        else:
            strategy = StrategyOutput.model_validate(data)
    except Exception:
        return (
            "<!DOCTYPE html><html><head><meta charset='utf-8'><title>Strategy Report</title></head>"
            "<body><h1>Strategy Report</h1><p>Unable to validate strategy data.</p></body></html>"
        )

    parts: list[str] = []
    parts.append("<!DOCTYPE html><html><head><meta charset='utf-8'><title>MarketScout Strategy Report</title>")
    parts.append(f"<style>{_STYLE}</style></head><body>")

    city = getattr(strategy, "city", "")
    industry = getattr(strategy, "industry", "")
    dq = getattr(strategy, "data_quality", None)
    parts.append("<h1>Executive Summary</h1>")
    parts.append(f"<p><strong>City:</strong> {_escape(city)} &emsp; <strong>Industry:</strong> {_escape(industry)}</p>")
    if dq is not None:
        parts.append(
            f"<p><strong>Data quality:</strong> freshness {getattr(dq, 'freshness_window_days', 0)} days | "
            f"coverage {getattr(dq, 'coverage_score', 0):.2f} | source mix {getattr(dq, 'source_mix_score', 0):.2f}</p>"
        )
    signals = getattr(strategy, "signals_used", None)
    if signals is not None:
        parts.append(
            f"<p><strong>Signals:</strong> {getattr(signals, 'headlines_count', 0)} headlines, "
            f"{getattr(signals, 'jobs_count', 0)} jobs, "
            f"{getattr(signals, 'news_sources_count', 0)} news sources, "
            f"{getattr(signals, 'job_companies_count', 0)} job companies.</p>"
        )

    if signal_analysis:
        parts.append("<h2>Signal Analysis</h2>")
        sig = signal_analysis.get("signals") or {}
        parts.append(
            f"<p><strong>Headlines:</strong> {sig.get('headlines_count', 0)} | <strong>Jobs:</strong> {sig.get('jobs_count', 0)} | "
            f"<strong>Unique news sources:</strong> {sig.get('unique_news_sources', 0)} | <strong>Unique companies:</strong> {sig.get('unique_companies', 0)}</p>"
        )

        fetch_status = signal_analysis.get("fetch_status") or {}
        if fetch_status:
            _STATUS_COLOR = {"live": "#2d7a2d", "cached": "#a06000", "failed": "#c0392b"}
            parts.append(
                "<p><strong>Fetch status:</strong></p>"
                "<table><thead><tr><th>Source</th><th>Provider</th><th>Status</th><th>Note</th></tr></thead><tbody>"
            )
            for source, entry in fetch_status.items():
                provider = _escape(entry.get("provider", ""))
                status = entry.get("status", "")
                color = _STATUS_COLOR.get(status, "#333")
                note = _escape((entry.get("error") or "")[:80])
                parts.append(
                    f"<tr><td>{_escape(source)}</td><td>{provider}</td>"
                    f"<td><span style='color:{color};font-weight:bold'>{_escape(status)}</span></td>"
                    f"<td>{note}</td></tr>"
                )
            parts.append("</tbody></table>")

        run_meta = signal_analysis.get("run_metadata") or {}
        if run_meta:
            parts.append(
                f"<p><strong>Run:</strong> started {_escape(run_meta.get('started_at_iso', ''))} &nbsp;|&nbsp; "
                f"{run_meta.get('duration_ms', 0)} ms &nbsp;|&nbsp; "
                f"deterministic={run_meta.get('deterministic', False)} &nbsp;|&nbsp; "
                f"cache_used={run_meta.get('cache_used', False)}</p>"
            )

        keyword_hits = signal_analysis.get("keyword_hits") or {}
        if keyword_hits:
            parts.append("<p><strong>Keyword hits (tag → count):</strong></p><ul>")
            for tag, count in sorted(keyword_hits.items()):
                parts.append(f"<li>{_escape(tag)}: {count}</li>")
            parts.append("</ul>")
        top_tags = signal_analysis.get("top_tags") or []
        if top_tags:
            parts.append(
                "<p><strong>Top bottleneck tags:</strong> "
                + ", ".join(_escape(t) for t in top_tags[:5])
                + "</p>"
            )

    _SUPPORT_COLOR = {"strong": "#1a7a1a", "moderate": "#a06000", "weak": "#c0392b"}

    _REC_COLOR = {
        "pursue_now":       "#1a7a1a",
        "validate_further": "#a06000",
        "monitor":          "#555555",
        "deprioritize":     "#c0392b",
    }

    opps = getattr(strategy, "opportunity_map", [])
    parts.append("<h2>Opportunity Map</h2>")
    if opps:
        parts.append(
            "<table><thead><tr><th>Title</th><th>Pain</th><th>ROI</th><th>Conf</th>"
            "<th>Support</th><th>Recommendation</th><th>Type</th></tr></thead><tbody>"
        )
        for o in opps:
            raw_title = (getattr(o, "title", "") or "")[:40]
            padded = getattr(o, "is_padded", False)
            title = _escape(raw_title) + (" ⚠" if padded else "")
            pain = getattr(o, "pain_score", 0)
            roi = getattr(o, "roi_signal", 0)
            conf = getattr(o, "confidence", 0)
            support = getattr(o, "support_level", "moderate")
            recommendation = getattr(o, "recommendation", "monitor")
            opp_type = getattr(o, "opportunity_type", "operational")
            support_color = _SUPPORT_COLOR.get(support, "#333")
            rec_color = _REC_COLOR.get(recommendation, "#333")
            parts.append(
                f"<tr><td>{title}</td><td>{pain}</td><td>{roi}</td><td>{conf:.2f}</td>"
                f"<td><span style='color:{support_color};font-weight:bold'>{_escape(support)}</span></td>"
                f"<td><span style='color:{rec_color};font-weight:bold'>{_escape(recommendation)}</span></td>"
                f"<td>{_escape(opp_type)}</td></tr>"
            )
        parts.append("</tbody></table>")
        parts.append("<p><small>⚠ = template-padded opportunity (limited direct evidence)</small></p>")
    else:
        parts.append("<p><em>No opportunities.</em></p>")

    for i, o in enumerate(opps, 1):
        title = _escape(getattr(o, "title", "") or f"Opportunity {i}")
        parts.append(f"<h3>{i}. {title}</h3>")

        # Signal quality and identity block
        support = getattr(o, "support_level", "moderate")
        age_avg = getattr(o, "signal_age_days_avg", None)
        unique_src = getattr(o, "unique_sources_count", 0)
        is_padded = getattr(o, "is_padded", False)
        recommendation = getattr(o, "recommendation", "monitor")
        opp_type = getattr(o, "opportunity_type", "operational")
        trend_key = getattr(o, "trend_key", "") or ""
        age_str = f"{age_avg:.0f}d avg age" if age_avg is not None else "age unknown"
        support_color = _SUPPORT_COLOR.get(support, "#333")
        rec_color = _REC_COLOR.get(recommendation, "#333")
        parts.append(
            f"<p><strong>Signal quality:</strong> "
            f"<span style='color:{support_color};font-weight:bold'>{_escape(support.upper())}</span> "
            f"&nbsp;|&nbsp; {_escape(age_str)} &nbsp;|&nbsp; {unique_src} unique source(s)</p>"
        )
        key_frag = f" &nbsp;|&nbsp; key: <code>{_escape(trend_key)}</code>" if trend_key else ""
        parts.append(
            f"<p style='background:#f0f4ff;padding:0.35rem 0.6rem;border-left:3px solid {rec_color};margin:0.4rem 0'>"
            f"<strong>Decision:</strong> "
            f"<span style='color:{rec_color};font-weight:bold'>{_escape(recommendation)}</span>"
            f" &nbsp;|&nbsp; type: <code>{_escape(opp_type)}</code>{key_frag}</p>"
        )
        if is_padded:
            parts.append(
                "<p style='background:#fff3cd;padding:0.4rem;border-left:3px solid #f0ad4e'>"
                "<strong>Template-padded</strong> — no direct keyword evidence found for this bottleneck. "
                "Treat as hypothesis only; do not act without additional validation.</p>"
            )

        parts.append(f"<p><strong>Problem:</strong> {_escape(getattr(o, 'problem', ''))}</p>")
        evidence_list = getattr(o, "evidence", []) or []
        if evidence_list:
            parts.append("<p><strong>Evidence:</strong></p><ul>")
            for e in evidence_list:
                tit = _escape((getattr(e, "title", "") or "")[:70])
                link = getattr(e, "link", "") or "#"
                src = getattr(e, "source", "")
                parts.append(f"<li><a href='{_escape(link)}'>{tit}</a> ({src})</li>")
            parts.append("</ul>")
        bc = getattr(o, "business_case", None)
        if bc:
            parts.append(f"<p><strong>Business case:</strong> {_escape(getattr(bc, 'savings_range_annual', ''))}</p>")
            assumptions = getattr(bc, "assumptions", []) or []
            if assumptions:
                parts.append("<ul>")
                for a in assumptions:
                    parts.append(f"<li>{_escape(a)}</li>")
                parts.append("</ul>")
        sb = getattr(o, "score_breakdown", None)
        if sb is not None:
            parts.append(
                f"<p><strong>Score breakdown:</strong> signal_frequency={getattr(sb, 'signal_frequency', 0):.2f} | "
                f"source_diversity={getattr(sb, 'source_diversity', 0):.2f} | job_role_density={getattr(sb, 'job_role_density', 0):.2f}</p>"
            )
        br = getattr(o, "brief", None)
        if br is not None:
            parts.append(
                "<table style='margin-top:0.5rem;background:#f9f9f9'>"
                "<thead><tr><th colspan='2'>Brief</th></tr></thead><tbody>"
            )
            for label, val in [
                ("Likely buyer", getattr(br, "likely_buyer", "")),
                ("Pain theme", getattr(br, "pain_theme", "")),
                ("Commercial angle", getattr(br, "commercial_angle", "")),
                ("Suggested next step", getattr(br, "suggested_next_step", "")),
                ("Why now", getattr(br, "why_now", "")),
            ]:
                parts.append(f"<tr><td style='white-space:nowrap;font-weight:bold'>{label}</td><td>{_escape(val)}</td></tr>")
            parts.append("</tbody></table>")
        actions = getattr(o, "suggested_actions", []) or []
        if actions:
            parts.append("<p><strong>Suggested actions:</strong></p><ul>")
            for act in actions:
                parts.append(f"<li>{_escape(act)}</li>")
            parts.append("</ul>")
        opp_leads = getattr(o, "leads", []) or []
        if opp_leads:
            parts.append("<p><strong>Potential leads:</strong></p><ul>")
            for lead in opp_leads:
                company = _escape(getattr(lead, "company_name", ""))
                reason = _escape(getattr(lead, "reason", ""))
                sig_type = _escape(getattr(lead, "signal_type", ""))
                score = getattr(lead, "priority_score", 0)
                parts.append(
                    f"<li><strong>{company}</strong> — {reason} "
                    f"<span style='color:#666'>(signal: {sig_type}, score: {score:.1f})</span></li>"
                )
            parts.append("</ul>")

    parts.append("<h2>Leads</h2>")
    parts.append("<p>See <strong>leads.csv</strong> for company-level leads (top companies by readiness).</p>")

    parts.append("<h2>Sources</h2><ul>")
    seen: set[str] = set()
    for o in opps:
        for e in getattr(o, "evidence", []) or []:
            link = getattr(e, "link", "") or ""
            if link and link != "#" and link not in seen:
                seen.add(link)
                tit = (getattr(e, "title", "") or link)[:60]
                parts.append(f"<li><a href='{_escape(link)}'>{_escape(tit)}</a></li>")
    parts.append("</ul>")

    parts.append("</body></html>")
    return "\n".join(parts)


def _escape(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
