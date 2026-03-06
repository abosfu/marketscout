"""Strategy generation: deterministic opportunity map from headlines + jobs (v2.0). Optional LLM fallback."""

from __future__ import annotations

import json
import os
import random
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Any, Literal

from marketscout.brain.schema import (
    AI_CATEGORIES,
    BusinessCase,
    DataQuality,
    EvidenceItem,
    OpportunityItem,
    ScoreBreakdown,
    SignalsUsed,
    StrategyOutput,
    STRATEGY_VERSION,
    get_json_schema,
)
from marketscout.config import get_strategy_mode
from marketscout.templates.industries import IndustryTemplate, get_template

# Keywords in job titles that imply manual ops / labor pressure (for roi_signal)
JOBS_MANUAL_OPS_KEYWORDS = (
    "labor", "labour", "superintendent", "coordinator", "manager",
    "construction", "retail", "store", "warehouse", "driver",
    "technician", "operator", "assistant", "admin", "data entry", "scheduling",
)
# Bottleneck keywords that imply high automation potential (admin, data entry, scheduling)
HIGH_AUTOMATION_KEYWORDS = ("labor", "shortage", "admin", "data entry", "scheduling", "skill", "coordinator")
# Lower automation (strategy, partnership, regulatory)
LOW_AUTOMATION_KEYWORDS = ("partnership", "strategy", "regulatory", "permit", "zoning", "compliance")


def _parse_timestamp(ts: str) -> datetime | None:
    """Parse a timestamp string from RSS or ISO-8601 into a datetime, or return None."""
    ts = (ts or "").strip()
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        pass
    try:
        return parsedate_to_datetime(ts)
    except Exception:
        return None


def _compute_signals_used(headlines: list[dict[str, Any]], jobs: list[dict[str, Any]]) -> SignalsUsed:
    """Compute v2.0 SignalsUsed from headlines and jobs."""
    news_sources = {
        (h.get("source") or "").strip() or (h.get("link") or "").strip()
        for h in headlines
        if (h.get("source") or h.get("link"))
    }
    job_companies = {
        (j.get("company") or "").strip()
        for j in jobs
        if (j.get("company") or "").strip()
    }
    return SignalsUsed(
        headlines_count=len(headlines),
        jobs_count=len(jobs),
        news_sources_count=len(news_sources),
        job_companies_count=len(job_companies) if job_companies else (1 if jobs else 0),
    )


def _compute_data_quality(
    headlines: list[dict[str, Any]],
    jobs: list[dict[str, Any]],
    signals_used: SignalsUsed,
) -> DataQuality:
    """Compute freshness_window_days, coverage_score, source_mix_score."""
    timestamps: list[datetime] = []
    for h in headlines:
        ts = _parse_timestamp(h.get("published", ""))
        if ts is not None:
            timestamps.append(ts)
    for j in jobs:
        ts = _parse_timestamp(j.get("published", ""))
        if ts is not None:
            timestamps.append(ts)
    if timestamps:
        delta = max(timestamps) - min(timestamps)
        freshness_window_days = max(0, delta.days)
    else:
        freshness_window_days = 0

    total_signals = signals_used.headlines_count + signals_used.jobs_count
    coverage_score = min(1.0, (total_signals / 20.0) * 0.5 + 0.5) if total_signals else 0.0

    total_sources = signals_used.news_sources_count + signals_used.job_companies_count
    source_mix_score = min(1.0, total_sources / 12.0) if total_sources else 0.0

    return DataQuality(
        freshness_window_days=freshness_window_days,
        coverage_score=round(coverage_score, 3),
        source_mix_score=round(source_mix_score, 3),
    )


def _automation_potential_from_tag(bottleneck: str, evidence_titles: str) -> float:
    """Return 0-10 automation potential: high for admin/data/scheduling, low for strategy/regulatory."""
    low = bottleneck.lower()
    titles = evidence_titles.lower()
    base = 5.0
    for kw in HIGH_AUTOMATION_KEYWORDS:
        if kw in low or kw in titles:
            base += 1.2
            break
    for kw in LOW_AUTOMATION_KEYWORDS:
        if kw in low or kw in titles:
            base -= 1.5
            break
    return max(0.0, min(10.0, round(base, 1)))


def _roi_signal_from_jobs(jobs: list[dict[str, Any]], evidence_from_jobs: int) -> float:
    """ROI signal 0-10: job density and manual-ops keyword presence."""
    if not jobs:
        return max(0.0, min(10.0, 2.0 + evidence_from_jobs * 0.5))
    text = " ".join((j.get("title") or "").lower() for j in jobs[:25])
    score = 3.0
    for kw in JOBS_MANUAL_OPS_KEYWORDS:
        if kw in text:
            score += 0.5
    return max(0.0, min(10.0, round(score + evidence_from_jobs * 0.3, 1)))


def _confidence_single(evidence_count: int, has_headline: bool, has_job: bool, freshness_days: int) -> float:
    """Per-opportunity confidence from evidence count, source mix, and freshness."""
    count_factor = min(1.0, evidence_count / 5.0) * 0.5
    mix = 0.2 if (has_headline and has_job) else (0.1 if (has_headline or has_job) else 0.0)
    freshness = max(0.0, 1.0 - freshness_days / 90.0) * 0.3
    return max(0.0, min(1.0, round(count_factor + mix + freshness, 3)))


def build_signal_analysis(
    headlines: list[dict[str, Any]],
    jobs: list[dict[str, Any]],
    city: str,
    industry: str,
    template: IndustryTemplate | None = None,
    *,
    run_metadata: dict[str, Any] | None = None,
    fetch_status: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Build signal_analysis.json payload.
    Includes: city, industry, signals counts, keyword_hits, derived_tags.
    Optionally includes run_metadata and fetch_status when provided.
    """
    if template is None:
        template = get_template(industry)
    keyword_to_bottleneck = template.keyword_to_bottleneck() if template else {}
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
    unique_news_sources = {
        (h.get("source") or "").strip() or (h.get("link") or "").strip()
        for h in headlines
        if (h.get("source") or h.get("link"))
    }
    unique_companies = {
        (j.get("company") or "").strip()
        for j in jobs
        if (j.get("company") or "").strip()
    }
    keyword_hits: dict[str, int] = {}
    derived_tags: dict[str, int] = {}
    for kw, tag in keyword_to_bottleneck.items():
        count = 0
        for h in headlines:
            if kw in ((h.get("title") or "").lower()):
                count += 1
        for j in jobs:
            if kw in ((j.get("title") or "").lower()):
                count += 1
        if count > 0:
            keyword_hits[tag] = keyword_hits.get(tag, 0) + count
            derived_tags[tag] = derived_tags.get(tag, 0) + count

    result: dict[str, Any] = {
        "city": city,
        "industry": industry,
        "signals": {
            "headlines_count": len(headlines),
            "jobs_count": len(jobs),
            "unique_news_sources": len(unique_news_sources),
            "unique_companies": len(unique_companies),
        },
        "keyword_hits": keyword_hits,
        "derived_tags": derived_tags,
    }
    if run_metadata is not None:
        result["run_metadata"] = run_metadata
    if fetch_status is not None:
        result["fetch_status"] = fetch_status
    return result


def _bottleneck_to_ai_category(bottleneck: str, template: IndustryTemplate) -> str:
    """Map bottleneck label to one of template's ai_categories_allowed."""
    allowed = list(template.ai_categories_allowed) if template else list(AI_CATEGORIES)
    low = bottleneck.lower()
    if "labor" in low or "wage" in low or "shortage" in low or "staff" in low:
        for c in ("Operational efficiency", "Cost reduction"):
            if c in allowed:
                return c
    if "permit" in low or "regulat" in low or "compliance" in low:
        for c in ("Regulatory & permits", "Risk mitigation"):
            if c in allowed:
                return c
    if "supply" in low or "logistics" in low:
        for c in ("Operational efficiency", "Cost reduction"):
            if c in allowed:
                return c
    return allowed[0] if allowed else "Operational efficiency"


def _build_opportunity_map(
    headlines: list[dict[str, Any]],
    jobs: list[dict[str, Any]],
    industry: str,
    city: str,
    template: IndustryTemplate,
    data_quality: DataQuality,
    *,
    deterministic: bool = False,
) -> list[OpportunityItem]:
    """
    Build 5-8 opportunities from headlines + jobs using template keyword_map.
    Evidence only from provided headlines/jobs. Sorted by (pain_score + roi_signal)/2, then confidence.
    When deterministic=True, use stable ordering for keywords and sort opportunities deterministically.
    """
    keyword_to_bottleneck = template.keyword_to_bottleneck() if template else {}
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
    kw_items = sorted(keyword_to_bottleneck.items()) if deterministic else list(keyword_to_bottleneck.items())

    # Collect (bottleneck, evidence_list) from headlines and jobs
    bucket: dict[str, list[EvidenceItem]] = {}
    used_headline_links: set[str] = set()
    used_job_links: set[str] = set()

    for h in headlines:
        title = (h.get("title") or "").strip()
        link = (h.get("link") or "#").strip()
        if not title:
            continue
        title_lower = title.lower()
        for kw, problem in kw_items:
            if kw in title_lower:
                key = problem
                if key not in bucket:
                    bucket[key] = []
                if link not in used_headline_links and len(bucket[key]) < 5:
                    bucket[key].append(EvidenceItem(title=title, link=link, source="headline"))
                    used_headline_links.add(link)
                break

    for j in jobs:
        title = (j.get("title") or "").strip()
        link = (j.get("link") or "#").strip()
        if not title:
            continue
        title_lower = title.lower()
        for kw, problem in kw_items:
            if kw in title_lower:
                key = problem
                if key not in bucket:
                    bucket[key] = []
                if link not in used_job_links and len(bucket[key]) < 5:
                    bucket[key].append(EvidenceItem(title=title, link=link, source="job"))
                    used_job_links.add(link)
                break

    # Build OpportunityItem for each bucket; ensure at least 1 evidence per opportunity
    opportunities: list[OpportunityItem] = []
    all_evidence_titles = " ".join(
        (h.get("title") or "") for h in headlines
    ) + " " + " ".join((j.get("title") or "") for j in jobs)
    bucket_iter = sorted(bucket.items()) if deterministic else bucket.items()
    for problem, evidence_list in bucket_iter:
        if not evidence_list:
            continue
        evidence_list = evidence_list[:5]
        has_headline = any(e.source == "headline" for e in evidence_list)
        has_job = any(e.source == "job" for e in evidence_list)
        n_evidence = len(evidence_list)
        n_job_evidence = sum(1 for e in evidence_list if e.source == "job")
        raw_freq = min(1.0, n_evidence / 5.0)
        raw_div = 0.5 if (has_headline and has_job) else (0.25 if (has_headline or has_job) else 0.0)
        raw_job = (n_job_evidence / n_evidence) if n_evidence else 0.0
        total_raw = raw_freq + raw_div + raw_job
        if total_raw <= 0:
            sb = ScoreBreakdown(signal_frequency=1.0 / 3.0, source_diversity=1.0 / 3.0, job_role_density=1.0 / 3.0)
        else:
            sb = ScoreBreakdown(
                signal_frequency=round(raw_freq / total_raw, 3),
                source_diversity=round(raw_div / total_raw, 3),
                job_role_density=round(raw_job / total_raw, 3),
            )
        pain_score = 2.0 + 8.0 * (raw_freq * sb.signal_frequency + raw_div * sb.source_diversity + raw_job * sb.job_role_density)
        pain_score = min(10.0, round(pain_score, 1))
        automation = _automation_potential_from_tag(problem, all_evidence_titles)
        roi_signal = _roi_signal_from_jobs(jobs, 1 if has_job else 0)
        confidence = _confidence_single(n_evidence, has_headline, has_job, data_quality.freshness_window_days)
        ai_cat = _bottleneck_to_ai_category(problem, template)
        title_short = problem[:50] + ("..." if len(problem) > 50 else "")
        opportunities.append(
            OpportunityItem(
                title=title_short,
                problem=problem,
                ai_category=ai_cat,
                evidence=evidence_list,
                pain_score=pain_score,
                automation_potential=automation,
                roi_signal=roi_signal,
                confidence=confidence,
                business_case=BusinessCase(
                    savings_range_annual="$50k–$200k",
                    assumptions=[
                        "Based on signal density and industry template",
                        "Adjust with local cost data when available",
                    ],
                ),
                score_breakdown=sb,
            )
        )

    # Pad to 5-8 using template bottlenecks not yet covered
    bottleneck_list = list(keyword_to_bottleneck.values()) or [f"Market dynamics in {city}"]
    all_sources: list[tuple[str, str, Literal["headline", "job"]]] = []
    for h in headlines[:8]:
        all_sources.append((h.get("title") or "Headline", h.get("link") or "#", "headline"))
    for j in jobs[:8]:
        all_sources.append((j.get("title") or "Job", j.get("link") or "#", "job"))
    used_problems = {o.problem for o in opportunities}
    idx = 0
    while len(opportunities) < 5 and idx < len(bottleneck_list) * 2:
        p = bottleneck_list[idx % len(bottleneck_list)]
        if p not in used_problems:
            used_problems.add(p)
            ev = []
            if all_sources:
                for i in range(min(2, len(all_sources))):
                    t, link, src = all_sources[(idx + i) % len(all_sources)]
                    ev.append(EvidenceItem(title=t, link=link, source=src))
            if not ev and all_sources:
                t, link, src = all_sources[idx % len(all_sources)]
                ev = [EvidenceItem(title=t, link=link, source=src)]
            if not ev:
                ev = [EvidenceItem(title=f"{industry} context", link="#", source="headline")]
            opportunities.append(
                OpportunityItem(
                    title=p[:50] + ("..." if len(p) > 50 else ""),
                    problem=p,
                    ai_category=_bottleneck_to_ai_category(p, template),
                    evidence=ev,
                    pain_score=3.0,
                    automation_potential=5.0,
                    roi_signal=4.0,
                    confidence=0.3,
                    business_case=BusinessCase(
                        savings_range_annual="$30k–$120k",
                        assumptions=["Lower confidence; limited direct evidence"],
                    ),
                    score_breakdown=ScoreBreakdown(signal_frequency=1.0 / 3.0, source_diversity=1.0 / 3.0, job_role_density=1.0 / 3.0),
                )
            )
        idx += 1

    # Ensure at least 5 opportunities with generic fallbacks
    fallback_problems = [f"Market dynamics in {city}", f"{industry} operational challenges", "Regional demand and supply", "Cost and efficiency pressures", "Regulatory and compliance"]
    for fp in fallback_problems:
        if len(opportunities) >= 5:
            break
        if fp in used_problems:
            continue
        used_problems.add(fp)
        ev = [EvidenceItem(title=f"{industry} context", link="#", source="headline")]
        if all_sources:
            n = min(2, len(all_sources))
            ev = [EvidenceItem(title=all_sources[j % len(all_sources)][0], link=all_sources[j % len(all_sources)][1], source=all_sources[j % len(all_sources)][2]) for j in range(n)]
        opportunities.append(
            OpportunityItem(
                title=fp[:50],
                problem=fp,
                ai_category=_bottleneck_to_ai_category(fp, template),
                evidence=ev,
                pain_score=2.5,
                automation_potential=5.0,
                roi_signal=3.0,
                confidence=0.25,
                business_case=BusinessCase(
                    savings_range_annual="$30k–$100k",
                    assumptions=["Limited direct evidence; industry template"],
                ),
                score_breakdown=ScoreBreakdown(signal_frequency=1.0 / 3.0, source_diversity=1.0 / 3.0, job_role_density=1.0 / 3.0),
            )
        )

    # Sort by (pain_score + roi_signal)/2, then confidence; when deterministic use stable key (problem first)
    if deterministic:
        opportunities.sort(key=lambda o: (o.problem, -(o.pain_score + o.roi_signal) / 2.0, -o.confidence))
    else:
        opportunities.sort(key=lambda o: (-(o.pain_score + o.roi_signal) / 2.0, -o.confidence))
    return opportunities[:8]


def generate_mock_strategy(
    headlines: list[dict[str, Any]],
    industry: str,
    city: str,
    jobs: list[dict[str, Any]] | None = None,
    *,
    objective: str | None = None,
    location: str | None = None,
    template: IndustryTemplate | None = None,
    deterministic: bool = False,
) -> StrategyOutput:
    """Generate v2.0 strategy: opportunity_map 5-8 items, evidence from headlines and jobs only. objective/location optional. deterministic=True for reproducible order and scoring."""
    jobs = jobs or []
    if deterministic:
        random.seed(42)
        headlines = sorted(headlines, key=lambda h: (h.get("title") or ""))
        jobs = sorted(jobs, key=lambda j: (j.get("title") or ""))
    if template is None:
        template = get_template(industry)
    signals_used = _compute_signals_used(headlines, jobs)
    data_quality = _compute_data_quality(headlines, jobs, signals_used)
    opportunity_map = _build_opportunity_map(
        headlines, jobs, industry, city, template, data_quality, deterministic=deterministic
    )
    return StrategyOutput(
        strategy_version=STRATEGY_VERSION,
        city=city,
        industry=industry,
        opportunity_map=opportunity_map,
        signals_used=signals_used,
        data_quality=data_quality,
    )


def _call_openai_for_strategy(
    headlines: list[dict[str, Any]],
    industry: str,
    city: str,
    jobs: list[dict[str, Any]] | None = None,
    *,
    objective: str | None = None,
    location: str | None = None,
) -> StrategyOutput | None:
    """Call OpenAI to generate v2.0 strategy JSON; return None on any failure."""
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
- City: {city}
- Industry: {industry}
- Recent headlines (use ONLY these as evidence; cite title and link): {json.dumps(headlines[:15], indent=2)}
- Recent job listings (use ONLY these as evidence; cite title and link): {json.dumps(jobs[:15], indent=2)}

Produce a strategy as a single valid JSON object matching this schema (v2.0). Return only the JSON, no markdown.
Schema: {json.dumps(schema)}

Required: strategy_version "2.0", city, industry, opportunity_map (5-8 items), signals_used (headlines_count, jobs_count, news_sources_count, job_companies_count), data_quality (freshness_window_days, coverage_score, source_mix_score).
Each opportunity: title, problem, ai_category (from schema enum), evidence (list of {{title, link, source: "headline"|"job"}} - only use titles/links from the provided headlines and jobs), pain_score 0-10, automation_potential 0-10, roi_signal 0-10, confidence 0-1, business_case (savings_range_annual string, assumptions array)."""

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
        data["city"] = data.get("city") or city
        data["industry"] = data.get("industry") or industry
        return StrategyOutput.model_validate(data)
    except Exception:
        return None


def generate_strategy(
    headlines: list[dict[str, Any]],
    industry: str,
    city: str,
    jobs: list[dict[str, Any]] | None = None,
    *,
    objective: str | None = None,
    location: str | None = None,
    force_mock: bool | None = None,
    deterministic: bool = False,
) -> StrategyOutput:
    """
    Generate v2.0 strategy: opportunity_map from headlines and jobs. City and industry required; objective/location optional.
    deterministic=True for reproducible ordering and scoring (seed 42, sort signals by title).
    """
    if force_mock is None:
        mode = get_strategy_mode()
        force_mock = mode == "mock"
    if not force_mock:
        result = _call_openai_for_strategy(
            headlines, industry, city, jobs=jobs, objective=objective, location=location
        )
        if result is not None:
            return result
    return generate_mock_strategy(
        headlines, industry, city, jobs=jobs, objective=objective, location=location, deterministic=deterministic
    )
