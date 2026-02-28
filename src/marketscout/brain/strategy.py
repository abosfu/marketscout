"""Strategy generation: mock (deterministic) and optional LLM with fallback. Multi-signal (headlines + jobs)."""

from __future__ import annotations

import json
import os
from typing import Any

from marketscout.brain.schema import (
    AIMatch,
    PlanPhase,
    ProblemEvidence,
    ROINotes,
    ScoreBreakdown,
    SignalsUsed,
    StrategyOutput,
    STRATEGY_VERSION,
    get_json_schema,
)
from marketscout.config import get_strategy_mode
from marketscout.templates.industries import IndustryTemplate, get_template

# Fixed enum for AI match categories (mock only)
AI_CATEGORIES = (
    "Market entry",
    "Growth and scale",
    "Cost reduction",
    "Risk mitigation",
    "Regulatory & permits",
    "Operational efficiency",
    "Partnership and M&A",
)

# Keywords in job titles that imply manual ops / labor pressure (for jobs_signal_score)
JOBS_MANUAL_OPS_KEYWORDS = (
    "labor", "labour", "superintendent", "coordinator", "manager",
    "construction", "retail", "store", "warehouse", "driver",
    "technician", "operator", "assistant",
)
DEFAULT_WEIGHTS = {"news": 0.6, "jobs": 0.4}


def _mock_news_signal_score(headlines: list[dict[str, str]], location: str, base: int = 4) -> int:
    """Compute 0-10 score from headline keywords."""
    high_signal = ("labor", "housing", "rate", "inflation", "shortage", "crisis")
    medium_signal = ("supply chain", "permit", "skill", "material", "energy")
    title_text = " ".join((h.get("title") or "").lower() for h in headlines[:15])
    score = base
    for kw in high_signal:
        if kw in title_text:
            score += 1
    for kw in medium_signal:
        if kw in title_text:
            score += 1
    if "Vancouver" in location or "BC" in location:
        score += 1
    return min(10, max(0, score))


def _mock_jobs_signal_score(jobs: list[dict[str, str]]) -> int:
    """Compute 0-10 score from job titles (manual ops / labor demand signals)."""
    if not jobs:
        return 0
    text = " ".join((j.get("title") or "").lower() for j in jobs[:20])
    score = 2
    for kw in JOBS_MANUAL_OPS_KEYWORDS:
        if kw in text:
            score += 1
    return min(10, max(0, score))


def _combined_pain_score(
    news_score: int,
    jobs_score: int,
    weights: dict[str, float] | None = None,
) -> int:
    """Weighted combination; result 1-10."""
    w = weights or DEFAULT_WEIGHTS
    nw = w.get("news", 0.6)
    jw = w.get("jobs", 0.4)
    combined = nw * news_score + jw * jobs_score
    return min(10, max(1, round(combined)))


def _mock_problems_from_signals(
    headlines: list[dict[str, str]],
    jobs: list[dict[str, str]],
    industry: str,
    location: str,
    template: IndustryTemplate | None,
) -> list[ProblemEvidence]:
    """Infer 4-6 problems from headlines and jobs using template keyword_map; evidence from both."""
    keyword_to_bottleneck = (
        {k.lower(): v for k, v in template.keyword_map} if template and getattr(template, "keyword_map", None) else {}
    )
    if not keyword_to_bottleneck:
        keyword_to_bottleneck = {
            "labor": "Labor shortages and wage pressure",
            "housing": "Housing affordability and supply",
            "rate": "Interest rate and financing uncertainty",
            "supply chain": "Supply chain and logistics constraints",
            "permit": "Permitting and regulatory delays",
            "inflation": "Inflation and cost escalation",
            "skill": "Skills gap and workforce training",
            "material": "Material cost and availability",
        }
    # Normalize to lowercase keys
    keyword_to_bottleneck = {k.lower(): v for k, v in keyword_to_bottleneck.items()}

    used: set[str] = set()
    problems: list[ProblemEvidence] = []
    fallback_headlines = [
        {"title": f"Local {industry} update", "link": "https://example.com/1"},
        {"title": f"{location} market trends", "link": "https://example.com/2"},
        {"title": "Sector outlook report", "link": "https://example.com/3"},
        {"title": "Industry brief", "link": "https://example.com/4"},
    ]
    headline_sources = headlines[:10] if headlines else fallback_headlines
    job_sources = jobs[:10] if jobs else []

    # From headlines
    for h in headline_sources:
        title = (h.get("title") or "").lower()
        link = h.get("link") or "#"
        for kw, problem in keyword_to_bottleneck.items():
            if kw in title and problem not in used and len(problems) < 6:
                used.add(problem)
                problems.append(
                    ProblemEvidence(
                        problem=problem,
                        evidence_headline=h.get("title") or title,
                        evidence_link=link,
                        evidence_source="headline",
                    )
                )
                break

    # From jobs (map job title keywords to bottlenecks)
    for j in job_sources:
        title = (j.get("title") or "").lower()
        link = j.get("link") or "#"
        for kw, problem in keyword_to_bottleneck.items():
            if kw in title and problem not in used and len(problems) < 6:
                used.add(problem)
                problems.append(
                    ProblemEvidence(
                        problem=problem,
                        evidence_headline=j.get("title") or title,
                        evidence_link=link,
                        evidence_source="job",
                    )
                )
                break
        if len(problems) >= 6:
            break

    # Ensure at least 4 problems
    bottleneck_list = list(keyword_to_bottleneck.values()) or [f"Market dynamics in {location}"]
    all_sources = list(headline_sources) + list(job_sources)
    n_head = len(headline_sources)
    while len(problems) < 4:
        idx = len(problems)
        p = bottleneck_list[idx % len(bottleneck_list)]
        if p not in used:
            used.add(p)
        else:
            p = f"Market and regulatory dynamics in {location}"
        src = all_sources[idx % len(all_sources)] if all_sources else {"title": "Industry context", "link": "#"}
        src_idx = idx % len(all_sources) if all_sources else 0
        evidence_source = "headline" if (all_sources and src_idx < n_head) else "job"
        problems.append(
            ProblemEvidence(
                problem=p,
                evidence_headline=src.get("title", "Context"),
                evidence_link=src.get("link", "#"),
                evidence_source=evidence_source,
            )
        )

    return problems[:6]


def _mock_ai_matches(industry: str, objective: str, template: IndustryTemplate | None) -> list[AIMatch]:
    """Return AI match categories from template allowed list or fixed enum."""
    allowed = list(template.ai_categories_allowed) if template else list(AI_CATEGORIES)
    categories_used = [
        c for c in allowed
        if objective.lower() in c.lower() or c == "Market entry" or c == "Regulatory & permits"
    ]
    if not categories_used:
        categories_used = [allowed[0] if allowed else "Market entry", "Regulatory & permits"]
    approaches = [
        "Pilot in target neighbourhoods; partner with local suppliers.",
        "Align 30-day actions with quick wins; measure and iterate.",
        "Engage early with local permits; document assumptions.",
    ]
    return [
        AIMatch(category=f"{industry} — {categories_used[0]}", recommended_approach=approaches[0]),
        AIMatch(category=f"{industry} — {objective}", recommended_approach=approaches[1]),
        AIMatch(category="Regulatory & permits", recommended_approach=approaches[2]),
    ]


def _mock_plan_30_60_90(industry: str, objective: str) -> list[PlanPhase]:
    """Return a deterministic 30/60/90 plan."""
    return [
        PlanPhase(
            phase="30-day",
            actions=[
                "Define KPIs and baseline metrics",
                "Map key stakeholders and decision makers",
                "Draft initial scope and timeline",
            ],
        ),
        PlanPhase(
            phase="60-day",
            actions=[
                "Run pilot or proof of concept",
                "Gather feedback and adjust approach",
                "Lock budget and resource plan",
            ],
        ),
        PlanPhase(
            phase="90-day",
            actions=[
                "Scale or roll out next phase",
                "Review ROI assumptions vs actuals",
                "Plan next quarter priorities",
            ],
        ),
    ]


def _mock_roi_notes() -> ROINotes:
    """Return deterministic ROI notes."""
    return ROINotes(
        ranges="15–25% improvement in target metric within 6–12 months",
        assumptions=[
            "Stable labour and material costs",
            "No major regulatory changes",
            "Pilot conversion rates hold at scale",
        ],
    )


def generate_mock_strategy(
    headlines: list[dict[str, str]],
    industry: str,
    objective: str,
    location: str,
    jobs: list[dict[str, str]] | None = None,
    template: IndustryTemplate | None = None,
) -> StrategyOutput:
    """Generate strategy using mock logic. 4-6 problems; evidence from headlines and jobs; multi-signal score."""
    jobs = jobs or []
    if template is None:
        template = get_template(industry)

    problems = _mock_problems_from_signals(headlines, jobs, industry, location, template)
    news_score = _mock_news_signal_score(headlines, location)
    jobs_score = _mock_jobs_signal_score(jobs)
    combined = _combined_pain_score(news_score, jobs_score)
    signals_used = SignalsUsed(
        headlines_count=len(headlines),
        jobs_count=len(jobs),
        econ_used=False,
    )
    score_breakdown = ScoreBreakdown(
        news_signal_score=news_score,
        jobs_signal_score=jobs_score,
        combined_pain_score=combined,
        weights=dict(DEFAULT_WEIGHTS),
    )
    return StrategyOutput(
        strategy_version=STRATEGY_VERSION,
        pain_score=combined,
        signals_used=signals_used,
        score_breakdown=score_breakdown,
        problems=problems,
        ai_matches=_mock_ai_matches(industry, objective, template),
        plan_30_60_90=_mock_plan_30_60_90(industry, objective),
        roi_notes=_mock_roi_notes(),
    )


def _call_openai_for_strategy(
    headlines: list[dict[str, str]],
    industry: str,
    objective: str,
    location: str,
    jobs: list[dict[str, str]] | None = None,
) -> StrategyOutput | None:
    """Call OpenAI to generate strategy JSON; return None on any failure."""
    try:
        from openai import OpenAI
    except ImportError:
        return None
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key or not api_key.strip():
        return None
    jobs = jobs or []
    try:
        client = OpenAI(api_key=api_key)
        schema = get_json_schema()
        prompt = f"""You are a strategy analyst. Given:
- Industry: {industry}
- Objective: {objective}
- Location: {location}
- Recent headlines (use as evidence where relevant): {json.dumps(headlines[:10], indent=2)}
- Recent job listings (use as evidence where relevant): {json.dumps(jobs[:10], indent=2)}

Produce a strategy as a single valid JSON object matching this schema. Return only the JSON, no markdown.
Schema: {json.dumps(schema)}
Include: pain_score (1-10), signals_used (headlines_count, jobs_count, econ_used), score_breakdown (news_signal_score, jobs_signal_score, combined_pain_score, weights), problems (4-6 items; evidence_headline, evidence_link, optional evidence_source "headline" or "job"), ai_matches, plan_30_60_90 (exactly 3 phases), roi_notes."""

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
        )
        text = (response.choices[0].message.content or "").strip()
        if not text:
            return None
        if text.startswith("```"):
            lines = text.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines)
        data = json.loads(text)
        if "strategy_version" not in data:
            data["strategy_version"] = STRATEGY_VERSION
        return StrategyOutput.model_validate(data)
    except Exception:
        return None


def generate_strategy(
    headlines: list[dict[str, str]],
    industry: str,
    objective: str,
    location: str,
    jobs: list[dict[str, str]] | None = None,
    *,
    force_mock: bool | None = None,
) -> StrategyOutput:
    """
    Generate strategy: mode from config (mock/llm/auto) or force_mock.
    Uses headlines and optional jobs; multi-signal pain score in v1.1.
    """
    if force_mock is None:
        mode = get_strategy_mode()
        force_mock = mode == "mock"
    if not force_mock:
        result = _call_openai_for_strategy(headlines, industry, objective, location, jobs)
        if result is not None:
            return result
    return generate_mock_strategy(headlines, industry, objective, location, jobs=jobs)
