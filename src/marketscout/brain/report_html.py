"""Convert strategy JSON to a clean HTML report. Same sections as Markdown; minimal inline styling."""

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


def strategy_to_html(data: dict[str, Any] | StrategyOutput) -> str:
    """
    Convert strategy to HTML. Accepts dict or StrategyOutput.
    Validates first; on failure returns a minimal safe HTML page. Never raises.
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

    pain = getattr(strategy, "pain_score", 0)
    n_problems = len(getattr(strategy, "problems", []))
    parts.append("<h1>Executive Summary</h1>")
    parts.append(
        f"<p>This strategy report has a <strong>Pain Score</strong> of {pain}/10 "
        f"and identifies {n_problems} opportunity areas with evidence from recent headlines and job signals.</p>"
    )

    signals = getattr(strategy, "signals_used", None)
    if signals is not None:
        parts.append("<h2>Signals Used</h2><ul>")
        parts.append(f"<li><strong>Headlines count:</strong> {getattr(signals, 'headlines_count', 0)}</li>")
        parts.append(f"<li><strong>Jobs count:</strong> {getattr(signals, 'jobs_count', 0)}</li>")
        parts.append(f"<li><strong>Econ used:</strong> {getattr(signals, 'econ_used', False)}</li></ul>")

    breakdown = getattr(strategy, "score_breakdown", None)
    if breakdown is not None:
        parts.append("<h2>Score Breakdown</h2><ul>")
        parts.append(f"<li><strong>News signal score (0-10):</strong> {getattr(breakdown, 'news_signal_score', 0)}</li>")
        parts.append(f"<li><strong>Jobs signal score (0-10):</strong> {getattr(breakdown, 'jobs_signal_score', 0)}</li>")
        parts.append(f"<li><strong>Combined pain score (1-10):</strong> {getattr(breakdown, 'combined_pain_score', 0)}</li>")
        w = getattr(breakdown, "weights", {}) or {}
        parts.append(f"<li><strong>Weights:</strong> {w}</li></ul>")

    parts.append("<h2>Opportunity Map</h2>")
    problems = getattr(strategy, "problems", [])
    if problems:
        parts.append("<table><thead><tr><th>Problem</th><th>Evidence</th><th>Link</th></tr></thead><tbody>")
        for p in problems:
            prob = _escape(getattr(p, "problem", ""))
            head = _escape((getattr(p, "evidence_headline", "") or "")[:80])
            if len(getattr(p, "evidence_headline", "") or "") > 80:
                head += "..."
            link = getattr(p, "evidence_link", "") or "#"
            parts.append(f"<tr><td>{prob}</td><td>{head}</td><td><a href='{_escape(link)}'>{_escape(link[:50])}</a></td></tr>")
        parts.append("</tbody></table>")
    else:
        parts.append("<p><em>No problems documented.</em></p>")

    parts.append("<h2>AI Matches</h2>")
    for m in getattr(strategy, "ai_matches", []):
        cat = _escape(getattr(m, "category", "Category"))
        approach = _escape(getattr(m, "recommended_approach", ""))
        parts.append(f"<h3>{cat}</h3><p>{approach}</p>")

    parts.append("<h2>30/60/90 Plan</h2>")
    plan = getattr(strategy, "plan_30_60_90", [])
    for phase in plan:
        ph = _escape(getattr(phase, "phase", "Phase"))
        actions = getattr(phase, "actions", [])
        parts.append(f"<h3>{ph}</h3><ul>")
        for a in actions:
            parts.append(f"<li>{_escape(a)}</li>")
        parts.append("</ul>")

    parts.append("<h2>ROI Notes & Assumptions</h2>")
    roi = getattr(strategy, "roi_notes", None)
    if roi:
        ranges = _escape(getattr(roi, "ranges", "") or "")
        assumptions = getattr(roi, "assumptions", []) or []
        parts.append(f"<p><strong>Ranges:</strong> {ranges}</p><p><strong>Assumptions:</strong></p><ul>")
        for a in assumptions:
            parts.append(f"<li>{_escape(a)}</li>")
        parts.append("</ul>")
    else:
        parts.append("<p><em>No ROI notes.</em></p>")

    parts.append("<h2>Sources</h2><ul>")
    seen: set[str] = set()
    for p in problems:
        link = getattr(p, "evidence_link", "") or ""
        if link and link != "#" and link not in seen:
            seen.add(link)
            head = (getattr(p, "evidence_headline", "") or link)[:60]
            parts.append(f"<li><a href='{_escape(link)}'>{_escape(head)}</a></li>")
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
