"""Strategy generation: deterministic opportunity map from headlines + jobs (v2.0). Optional LLM fallback."""

from __future__ import annotations

import json
import os
import random
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Literal

from marketscout.backend.schema import (
    AI_CATEGORIES,
    BusinessCase,
    DataQuality,
    EvidenceItem,
    Lead,
    OpportunityBrief,
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

# Fixed scoring weights for pain_score (transparent, reproducible).
# pain_score = 2.0 + 8.0 * (W_FREQ*raw_freq + W_DIV*raw_div_norm + W_JOB*raw_job)
# where each component is normalised to [0, 1]; max weighted = 1.0, max pain_score = 10.0.
_W_FREQ: float = 0.5   # weight for evidence frequency (raw_freq in [0,1])
_W_DIV: float = 0.3    # weight for source diversity (raw_div_norm in [0,1])
_W_JOB: float = 0.2    # weight for job-role density (raw_job in [0,1])

# Signal freshness thresholds (days). Used for per-opportunity confidence and support_level.
_FRESHNESS_VERY_FRESH_DAYS: int = 7    # < 7 days: very fresh
_FRESHNESS_FRESH_DAYS: int = 30        # < 30 days: fresh
_FRESHNESS_MODERATE_DAYS: int = 90    # < 90 days: moderate; >= 90 days: stale

# ── Opportunity brief ──────────────────────────────────────────────────────────

# Default decision-maker persona per industry
_BUYER_MAP: dict[str, str] = {
    "Construction": "Operations Manager / Site Supervisor",
    "Retail": "Store Ops Lead / Regional Manager",
    "Healthcare": "Clinic Administrator / Operations Director",
    "Technology": "VP Engineering / Product Lead",
    "Real Estate": "Property Manager / Brokerage Principal",
    "Manufacturing": "Plant Manager / Operations Director",
    "Professional Services": "Managing Partner / Practice Lead",
}

# Commercial angle fallback by AI category (used when problem-specific angle is unavailable)
_COMMERCIAL_MAP: dict[str, str] = {
    "Operational efficiency": "Workflow automation, scheduling software, or process integration",
    "Cost reduction": "Cost-reduction consulting, outsourcing, or efficiency SaaS",
    "Risk mitigation": "Compliance monitoring, risk assessment tooling, or managed services",
    "Regulatory & permits": "Permitting workflow software, compliance tooling, or advisory services",
    "Market entry": "Market intelligence, go-to-market advisory, or partner-search services",
    "Growth and scale": "Capacity-building platforms, staffing tools, or strategic consulting",
    "Partnership and M&A": "Deal sourcing, due-diligence tooling, or partnership advisory",
}

# Corporate suffix regex for extracting company names from news headlines.
# Matches patterns like "Acme Corp", "Pacific Coast Construction Inc.", "BuildRight Group".
_CORP_SUFFIX_RE = re.compile(
    r"\b([A-Z][a-zA-Z&'.\-]*(?:\s+[A-Z][a-zA-Z&'.\-]*){0,3})"
    r"\s+(?:Inc|Corp|Ltd|LLC|Group|Co|Company|Services|Solutions|Systems|"
    r"Technologies|Tech|Consulting|Holdings|Partners|Associates|"
    r"Construction|Contracting|Staffing|Logistics|Industries|Enterprises)\.?",
)

# Opportunity type derived from AI category
_OPPORTUNITY_TYPE_MAP: dict[str, str] = {
    "Operational efficiency": "operational",
    "Cost reduction":         "operational",
    "Risk mitigation":        "compliance",
    "Regulatory & permits":   "compliance",
    "Market entry":           "strategic",
    "Growth and scale":       "strategic",
    "Partnership and M&A":    "strategic",
}


def _slugify(s: str) -> str:
    """Convert a string to a lowercase underscore slug for stable key generation."""
    s = s.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_")


def _make_trend_key(problem: str, ai_category: str, is_padded: bool) -> str:
    """
    Compute a stable canonical identifier for cross-run opportunity tracking.

    Format:
      Real opportunities:   "{category_slug}::{problem_slug}"
      Padded opportunities: "padded::{problem_slug}"

    Stability guarantees:
      - Uses the full problem string, not the truncated title.
      - City-specific text is stripped from padded fallback labels
        (e.g. "Market dynamics in Vancouver" → "padded::market_dynamics").
      - Lowercase + non-alphanumeric chars collapsed to underscores.
      - Deterministic: same inputs always produce the same key.
    """
    # Strip trailing city references from padded labels ("... in Vancouver")
    prob_clean = re.sub(r"\bin\s+\w[\w\s]*$", "", problem, flags=re.IGNORECASE).strip()
    prob_slug = _slugify(prob_clean or problem)
    if is_padded:
        return f"padded::{prob_slug}"
    return f"{_slugify(ai_category)}::{prob_slug}"


def _classify_recommendation(
    support_level: str,
    confidence: float,
    pain_score: float,
    is_padded: bool,
    avg_age_days: float | None,
) -> str:
    """
    Rule-based decision recommendation integrating all quality signals.

    Rules evaluated in priority order:
      deprioritize    — padded; or weak + low confidence (<0.35); or stale + low pain (<5.0)
      pursue_now      — strong support + confidence >=0.60 + pain >=6.0 + fresh (<30d)
      validate_further— moderate-or-better support + confidence >=0.35
      monitor         — everything else
    """
    # 1. Deprioritize: padded noise, very weak evidence, or stale low-pain signal
    if is_padded:
        return "deprioritize"
    if support_level == "weak" and confidence < 0.35:
        return "deprioritize"
    if avg_age_days is not None and avg_age_days >= _FRESHNESS_MODERATE_DAYS and pain_score < 5.0:
        return "deprioritize"
    # 2. Pursue now: strong signal with fresh, high-confidence evidence
    if (
        support_level == "strong"
        and confidence >= 0.60
        and pain_score >= 6.0
        and (avg_age_days is None or avg_age_days < _FRESHNESS_FRESH_DAYS)
    ):
        return "pursue_now"
    # 3. Validate further: has real evidence, worth investigating
    if support_level in ("moderate", "strong") and confidence >= 0.35:
        return "validate_further"
    # 4. Monitor: low confidence or borderline quality — watch across runs
    return "monitor"


def _classify_opportunity_type(ai_category: str) -> str:
    """Classify opportunity as operational, strategic, or compliance from its AI category."""
    return _OPPORTUNITY_TYPE_MAP.get(ai_category, "operational")


def _build_suggested_actions(
    problem: str,
    opportunity_type: str,
    recommendation: str,
    support_level: str,
    trend_key: str = "",
) -> list[str]:
    """
    Return 1–3 specific, actionable next steps grounded in recommendation, type, and support.

    Pure function — deterministic, no LLM. Reuses problem text for specificity.
    """
    _STOP = {"and", "or", "the", "a", "an", "in", "of", "for", "to", "with", "by", "from"}
    words = [w for w in re.sub(r"[^a-z0-9 ]+", " ", problem.lower()).split() if w not in _STOP]
    short_label = " ".join(words[:4]) if words else problem[:35].lower()

    if recommendation == "deprioritize":
        return ["Do not invest resources yet — signal quality is insufficient to justify action"]

    if recommendation == "pursue_now":
        if opportunity_type == "strategic":
            return [
                f"Map the competitive landscape for '{short_label}' — identify who is solving this and where the gap is",
                "Engage 3–5 senior buyers (VP/Director level) via warm intro or targeted LinkedIn outreach",
                "Draft a one-pager on your differentiated angle; share with a trusted contact for feedback this week",
            ]
        if opportunity_type == "compliance":
            return [
                f"Confirm enforcement timeline and scope with a regulatory specialist for '{short_label}'",
                "Identify affected companies by searching for compliance/legal role postings in this space",
                "Build a compliance checklist or advisory brief and test it with 5 affected companies",
            ]
        # operational (default)
        return [
            "Pull top companies from leads.csv — job signal confirms active budget and hiring mandate",
            f"Build a targeted pilot offer for '{short_label}' and test with direct outbound this week",
            "Book 3 discovery calls this sprint; validate the pain point in the first 15 minutes",
        ]

    if recommendation == "validate_further":
        return [
            "Interview 3–5 operators in this space to confirm the problem exists at scale",
            f"Search job boards for roles related to '{short_label}' and check 60-day posting volume trend",
            "Re-run this analysis in 2 weeks; commit resources only if signal count and diversity increase",
        ]

    # monitor (default)
    kw = trend_key.split("::")[-1].replace("_", " ") if trend_key else short_label
    return [
        f"Set a weekly news alert for: '{kw}'",
        "Track job posting volume in this area; re-evaluate if postings increase 30%+ month-over-month",
    ]


def _extract_company_from_headline(title: str) -> str | None:
    """Extract a company name from a news headline using corporate suffix patterns."""
    m = _CORP_SUFFIX_RE.search(title)
    return m.group(0).strip() if m else None


def _build_leads_for_opportunity(
    problem: str,
    keywords: set[str],
    headlines: list[dict[str, Any]],
    jobs: list[dict[str, Any]],
    evidence: list[EvidenceItem],
) -> list[Lead]:
    """
    Identify top 3–5 companies relevant to this opportunity from existing signals.

    Matches jobs and headlines against opportunity keywords, extracts company names,
    deduplicates (case-insensitive), and ranks by signal strength + frequency.

    Jobs use the explicit 'company' field; headlines use regex corporate-suffix extraction.
    Jobs score 2.0 base (hiring = active budget intent); news scores 1.0 base.
    +1.0 bonus if the signal appears directly in the opportunity's evidence.
    +0.5 frequency bonus per additional signal from the same company.

    Pure function — deterministic, no ML, no external calls.
    """
    _STOP = {
        "and", "or", "the", "a", "an", "in", "of", "for", "to", "with",
        "by", "from", "at", "on", "is", "are", "was", "were",
    }

    # Build search terms: explicit bucket keywords (most reliable), or problem words as fallback
    if keywords:
        search_terms = {kw.lower() for kw in keywords}
    else:
        # Padded/fallback opportunities: derive terms from problem text
        search_terms = {
            w for w in re.sub(r"[^a-z0-9 ]+", " ", problem.lower()).split()
            if w not in _STOP and len(w) >= 4
        }

    if not search_terms:
        return []

    evidence_links: set[str] = {e.link for e in evidence if e.link and e.link != "#"}

    # company_key (lowercase) → candidate dict
    candidates: dict[str, dict] = {}

    def _upsert(company: str, base_score: float, reason: str, sig_type: str, sig_ref: str) -> None:
        cname = company.strip()
        key = cname.lower()
        if len(key) < 2:
            return
        if key in candidates:
            candidates[key]["priority_score"] = min(10.0, candidates[key]["priority_score"] + 0.5)
        else:
            candidates[key] = {
                "company_name": cname,
                "reason": reason,
                "signal_type": sig_type,
                "signal_reference": sig_ref[:80],
                "priority_score": min(10.0, base_score),
            }

    for j in jobs:
        company = (j.get("company") or "").strip()
        if not company:
            continue
        jtitle = (j.get("title") or "").lower()
        jlink = (j.get("link") or "#").strip()
        if not any(term in jtitle for term in search_terms):
            continue
        score = 2.0 + (1.0 if jlink in evidence_links else 0.0)
        _upsert(
            company,
            score,
            f"Hiring for '{(j.get('title') or 'role')[:50]}'",
            "job",
            (j.get("title") or "")[:80],
        )

    for h in headlines:
        htitle = (h.get("title") or "").strip()
        hlink = (h.get("link") or "#").strip()
        if not any(term in htitle.lower() for term in search_terms):
            continue
        company = _extract_company_from_headline(htitle)
        if not company:
            continue
        score = 1.0 + (1.0 if hlink in evidence_links else 0.0)
        _upsert(
            company,
            score,
            f"Mentioned in '{htitle[:50]}'",
            "news",
            htitle[:80],
        )

    if not candidates:
        return []

    sorted_entries = sorted(
        candidates.values(),
        key=lambda x: (-x["priority_score"], x["company_name"].lower()),
    )
    return [
        Lead(
            company_name=e["company_name"],
            reason=e["reason"],
            signal_type=e["signal_type"],
            signal_reference=e["signal_reference"],
            priority_score=round(e["priority_score"], 2),
        )
        for e in sorted_entries[:5]
    ]


def _build_problem_specific_commercial_angle(problem: str, ai_category: str) -> str:
    """
    Return a commercial angle grounded in the actual bottleneck problem,
    not just the AI category. Falls back to the category-level angle when
    no specific keyword matches.
    """
    low = problem.lower()
    if any(kw in low for kw in ("labor", "labour", "staff", "workforce", "wage", "hiring", "talent", "shortage")):
        return "Workforce management platforms, staffing SaaS, or labor analytics tooling"
    if any(kw in low for kw in ("permit", "regulat", "compliance", "zoning", "environmental")):
        return "Permitting workflow software, compliance monitoring, or regulatory advisory services"
    if any(kw in low for kw in ("supply chain", "logistics", "procurement", "material", "inventory")):
        return "Supply chain visibility software, procurement automation, or vendor management tooling"
    if any(kw in low for kw in ("cost", "inflation", "rate", "financing", "reimbursement", "margin", "pricing", "energy")):
        return "Cost analytics, financial modeling tools, or procurement optimization services"
    if any(kw in low for kw in ("technology", "digital", "omnichannel", "ecommerce", "infrastructure", "scale")):
        return "Digital transformation consulting, integration platforms, or SaaS tooling"
    if any(kw in low for kw in ("security", "cyber", "risk")):
        return "Cybersecurity tooling, risk assessment platforms, or managed security services"
    if any(kw in low for kw in ("competition", "market", "partnership", "growth", "differentiation", "funding")):
        return "Market intelligence platforms, go-to-market advisory, or strategic consulting"
    if any(kw in low for kw in ("skill", "training", "education")):
        return "Workforce training platforms, upskilling programs, or L&D consulting"
    return _COMMERCIAL_MAP.get(ai_category, "Software tools or consulting services addressing this bottleneck")


def _build_opportunity_brief(
    title: str,
    ai_category: str,
    pain_score: float,
    evidence: list[EvidenceItem],
    industry: str,
    *,
    avg_age_days: float | None = None,
    unique_sources_count: int = 0,
    support_level: str = "moderate",
    recommendation: str = "monitor",
) -> OpportunityBrief:
    """
    Derive a structured, deterministic decision brief from scoring and evidence.
    No LLM required — all fields come from template mappings and evidence metadata.
    avg_age_days, unique_sources_count, support_level, and recommendation ground the
    why_now field in actual signal quality data.
    """
    # Likely buyer: start from industry default, then refine from job titles in evidence
    buyer = _BUYER_MAP.get(industry, "Operations Manager / Decision-Maker")
    for e in evidence:
        if e.source != "job":
            continue
        jt = e.title.lower()
        if "director" in jt or " vp " in jt or "vice president" in jt:
            buyer = f"Director / VP — {industry}"
            break
        if "manager" in jt:
            buyer = f"Operations Manager — {industry}"
            break
        if "coordinator" in jt or "scheduler" in jt or "dispatcher" in jt:
            buyer = "Operations Coordinator (escalation path: Ops Manager)"
            break

    # pain_theme: the bottleneck label, cleaned up
    pain_theme = title.rstrip(".")

    # commercial_angle: problem-specific first, category fallback if no keyword match
    commercial_angle = _build_problem_specific_commercial_angle(title, ai_category)

    # suggested_next_step: weak support overrides pain ladder (evidence not strong enough to act on)
    if support_level == "weak":
        next_step = (
            "Validate signal quality before acting — evidence is thin or stale; "
            "run additional data collection to confirm the opportunity"
        )
    elif pain_score >= 8.0:
        next_step = (
            "Initiate direct outreach — signal strength is high; "
            "qualified buyers likely have active budget or mandate"
        )
    elif pain_score >= 6.0:
        next_step = "Qualify 3–5 target companies from leads.csv; validate pain in discovery calls"
    elif pain_score >= 4.0:
        next_step = "Run a second data collection pass; monitor signal trend before committing resources"
    else:
        next_step = "Watch signal over next 2–3 runs; low confidence — validate before pursuing"

    # why_now: analyst note leading with support verdict, grounded in evidence metadata
    n_ev = len(evidence)
    has_both = any(e.source == "headline" for e in evidence) and any(e.source == "job" for e in evidence)

    freshness_clause = ""
    if avg_age_days is not None:
        bucket = _freshness_bucket(avg_age_days)
        label_map = {
            "very_fresh": "very fresh",
            "fresh": "fresh",
            "moderate": "moderate recency",
            "stale": "stale — consider rerunning",
        }
        freshness_clause = f"signals avg {avg_age_days:.0f}d old ({label_map[bucket]})"

    source_clause = f"{unique_sources_count} unique sources" if unique_sources_count > 1 else ""

    # Lead phrase: support-level verdict first, evidence detail second
    if support_level == "strong":
        lead = f"Multi-source evidence confirms a real gap: {n_ev} signal{'s' if n_ev != 1 else ''} across news + jobs"
    elif support_level == "weak":
        lead = f"Thin evidence ({n_ev} signal{'s' if n_ev != 1 else ''}) — treat as early indicator only"
    else:
        # moderate — evidence-count based
        if n_ev >= 4 and has_both:
            lead = f"{n_ev} cross-type signals (news + jobs)"
        elif n_ev >= 3:
            lead = f"{n_ev} signals confirm the problem this cycle"
        elif n_ev >= 2:
            lead = "Signal present but narrow"
        else:
            lead = "Single-source signal; use as early indicator only"

    parts = [lead]
    if source_clause:
        parts.append(source_clause)
    if freshness_clause:
        parts.append(freshness_clause)
    why_now = "; ".join(parts)

    # Trailing context for moderate partial-coverage cases
    if support_level == "moderate":
        if n_ev >= 3 and not (n_ev >= 4 and has_both):
            why_now += " — cross-source coverage partial"
        elif n_ev < 3:
            why_now += " — confirm with additional run before treating as primary thesis"

    # Quality alert for weak multi-evidence
    if support_level == "weak" and n_ev > 1:
        why_now += " [low-confidence: verify before acting]"

    # Urgency addendum for strong pursue_now signals
    if support_level == "strong" and recommendation == "pursue_now":
        why_now += " — act now, quality thresholds met"

    return OpportunityBrief(
        likely_buyer=buyer,
        pain_theme=pain_theme,
        commercial_angle=commercial_angle,
        suggested_next_step=next_step,
        why_now=why_now,
    )


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


def _signal_age_days(published: str, now: datetime | None = None) -> float | None:
    """Return age of a signal in days from its published timestamp, or None if unparseable."""
    ts = _parse_timestamp(published)
    if ts is None:
        return None
    if now is None:
        now = datetime.now(tz=timezone.utc)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return max(0.0, (now - ts).total_seconds() / 86400.0)


def _freshness_bucket(age_days: float) -> str:
    """Classify signal age into a named bucket for display and decision logic."""
    if age_days < _FRESHNESS_VERY_FRESH_DAYS:
        return "very_fresh"
    if age_days < _FRESHNESS_FRESH_DAYS:
        return "fresh"
    if age_days < _FRESHNESS_MODERATE_DAYS:
        return "moderate"
    return "stale"


def _classify_support_level(
    evidence_count: int,
    has_headline: bool,
    has_job: bool,
    avg_age_days: float | None,
    unique_sources: int,
    is_padded: bool,
) -> str:
    """
    Classify signal quality as 'strong', 'moderate', or 'weak'.

    Weak when any of: padded, <2 evidence, stale (>=90 days avg), <2 unique sources.
    Strong when all of: >=4 evidence, both source types, >=3 unique sources, fresh (<30 days avg).
    Moderate: everything else.
    """
    if is_padded:
        return "weak"
    if evidence_count < 2:
        return "weak"
    if avg_age_days is not None and avg_age_days >= _FRESHNESS_MODERATE_DAYS:
        return "weak"
    if unique_sources < 2:
        return "weak"
    if (
        evidence_count >= 4
        and has_headline
        and has_job
        and unique_sources >= 3
        and (avg_age_days is None or avg_age_days < _FRESHNESS_FRESH_DAYS)
    ):
        return "strong"
    return "moderate"


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


def _confidence_single(
    evidence_count: int,
    has_headline: bool,
    has_job: bool,
    avg_age_days: float | None,
    unique_source_count: int,
) -> float:
    """
    Per-opportunity confidence from evidence count, cross-source mix,
    per-opportunity freshness, and unique source diversity.

    Weights sum to 1.0 at maximum:
      count_factor: up to 0.40 (evidence quantity, plateau at 5)
      mix:          0.15 if both headline+job, 0.08 if either
      freshness:    up to 0.30 (per-opportunity avg age, zero at 90+ days)
      source_div:   up to 0.15 (unique publishers/companies, plateau at 3)
    """
    count_factor = min(1.0, evidence_count / 5.0) * 0.40
    mix = 0.15 if (has_headline and has_job) else (0.08 if (has_headline or has_job) else 0.0)
    if avg_age_days is None:
        freshness = 0.10  # Unknown age: mild conservative penalty
    else:
        freshness = max(0.0, 1.0 - avg_age_days / _FRESHNESS_MODERATE_DAYS) * 0.30
    source_div = min(1.0, unique_source_count / 3.0) * 0.15
    return max(0.0, min(1.0, round(count_factor + mix + freshness + source_div, 3)))


def build_signal_analysis(
    headlines: list[dict[str, Any]],
    jobs: list[dict[str, Any]],
    city: str,
    industry: str,
    template: IndustryTemplate | None = None,
    *,
    run_metadata: dict[str, Any] | None = None,
    fetch_status: dict[str, Any] | None = None,
    strategy_mode: str | None = None,
) -> dict[str, Any]:
    """
    Build signal_analysis.json payload.
    Includes: city, industry, signals counts, keyword_hits, top_tags.
    Optionally includes run_metadata, fetch_status, and strategy_mode_config when provided.
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

    # top_tags: bottleneck labels ranked by total keyword hit count (replaces duplicate derived_tags)
    top_tags = sorted(keyword_hits.keys(), key=lambda t: -keyword_hits[t])

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
        "top_tags": top_tags,
    }
    if strategy_mode is not None:
        result["strategy_mode_config"] = strategy_mode
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
    *,
    deterministic: bool = False,
) -> list[OpportunityItem]:
    """
    Build 5-8 opportunities from headlines + jobs using template keyword_map.
    Evidence only from provided headlines/jobs. Sorted by (pain_score + roi_signal)/2, then confidence.
    When deterministic=True, use stable ordering for keywords and sort opportunities deterministically.

    Pain score uses a transparent linear formula:
        pain_score = 2.0 + 8.0 * (_W_FREQ*raw_freq + _W_DIV*raw_div_norm + _W_JOB*raw_job)
    where raw_div is normalised to [0,1] (raw_div * 2), so max weighted = 1.0 and max pain = 10.0.
    score_breakdown shows the proportional contribution of each weighted component.
    roi_signal and automation_potential are computed per-opportunity from that opportunity's evidence.
    Confidence is computed from per-opportunity freshness (not a global window).
    Signals can match multiple keywords — a signal contributes to every bottleneck whose keyword it contains.
    Padded/fallback opportunities are flagged with is_padded=True and support_level="weak".
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

    # Reverse map: bottleneck label → set of keywords (used to filter signals during padding)
    bottleneck_to_keywords: dict[str, set[str]] = {}
    for kw, bn in keyword_to_bottleneck.items():
        bottleneck_to_keywords.setdefault(bn, set()).add(kw)

    # Forward map: problem label → keywords that actually appeared in signals (for lead extraction)
    problem_to_keywords: dict[str, set[str]] = {}

    # Build per-signal metadata lookups (link → published timestamp, link → source name)
    link_to_published: dict[str, str] = {}
    link_to_source_name: dict[str, str] = {}
    for h in headlines:
        lnk = (h.get("link") or "#").strip()
        link_to_published[lnk] = h.get("published", "") or ""
        src_name = (h.get("source") or "").strip()
        if src_name and lnk != "#":
            link_to_source_name[lnk] = src_name
    for j in jobs:
        lnk = (j.get("link") or "#").strip()
        link_to_published[lnk] = j.get("published", "") or ""
        company = (j.get("company") or "").strip()
        if company and lnk != "#":
            link_to_source_name[lnk] = company

    # Fix the reference time once per run (avoids drift between opportunities in the same run)
    now = datetime.now(tz=timezone.utc)

    # Bucket signals by keyword → bottleneck.
    # Multi-keyword: a signal is added to EVERY bucket whose keyword appears in its title.
    # Per-bucket dedup: same link cannot appear twice in the same bucket.
    bucket: dict[str, list[EvidenceItem]] = {}
    bucket_link_sets: dict[str, set[str]] = {}

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
                    bucket_link_sets[key] = set()
                if link not in bucket_link_sets[key] and len(bucket[key]) < 5:
                    bucket[key].append(EvidenceItem(title=title, link=link, source="headline"))
                    bucket_link_sets[key].add(link)
                problem_to_keywords.setdefault(problem, set()).add(kw)
                # No break — allow a signal to match multiple bottlenecks

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
                    bucket_link_sets[key] = set()
                if link not in bucket_link_sets[key] and len(bucket[key]) < 5:
                    bucket[key].append(EvidenceItem(title=title, link=link, source="job"))
                    bucket_link_sets[key].add(link)
                problem_to_keywords.setdefault(problem, set()).add(kw)
                # No break — allow a signal to match multiple bottlenecks

    # Build OpportunityItem for each bucket with transparent per-opportunity scoring.
    opportunities: list[OpportunityItem] = []
    bucket_iter = sorted(bucket.items()) if deterministic else bucket.items()
    for problem, evidence_list in bucket_iter:
        if not evidence_list:
            continue
        evidence_list = evidence_list[:5]
        has_headline = any(e.source == "headline" for e in evidence_list)
        has_job = any(e.source == "job" for e in evidence_list)
        n_evidence = len(evidence_list)
        n_job_evidence = sum(1 for e in evidence_list if e.source == "job")

        # Per-opportunity freshness: average age of evidence signals in days
        ages: list[float] = []
        for e in evidence_list:
            age = _signal_age_days(link_to_published.get(e.link, ""), now=now)
            if age is not None:
                ages.append(age)
        avg_age_days: float | None = (sum(ages) / len(ages)) if ages else None

        # Per-opportunity unique source count (unique publishers / companies in evidence)
        source_names = {
            link_to_source_name.get(e.link, e.link)
            for e in evidence_list
            if e.link != "#"
        }
        unique_sources_count = len(source_names)

        # Raw score components (all normalised to [0, 1])
        raw_freq = min(1.0, n_evidence / 5.0)
        raw_div = 0.5 if (has_headline and has_job) else (0.25 if (has_headline or has_job) else 0.0)
        raw_div_n = raw_div * 2.0          # normalise [0, 0.5] → [0, 1.0]
        raw_job = (n_job_evidence / n_evidence) if n_evidence else 0.0

        # Transparent linear pain_score; max weighted = 1.0 → max pain = 10.0
        weighted = _W_FREQ * raw_freq + _W_DIV * raw_div_n + _W_JOB * raw_job
        pain_score = min(10.0, round(2.0 + 8.0 * weighted, 1))

        # score_breakdown: proportional contribution of each weighted component (sums to 1.0)
        if weighted > 0.0:
            sf = round((_W_FREQ * raw_freq) / weighted, 3)
            sd = round((_W_DIV * raw_div_n) / weighted, 3)
            jr = round(max(0.0, 1.0 - sf - sd), 3)
        else:
            sf = round(1.0 / 3.0, 3)
            sd = round(1.0 / 3.0, 3)
            jr = round(max(0.0, 1.0 - sf - sd), 3)
        sb = ScoreBreakdown(signal_frequency=sf, source_diversity=sd, job_role_density=jr)

        # Per-opportunity roi_signal: use only job items that appear in this opportunity's evidence
        job_ev_links = {e.link for e in evidence_list if e.source == "job"}
        opp_jobs = [j for j in jobs if (j.get("link") or "#") in job_ev_links]
        roi_signal = _roi_signal_from_jobs(opp_jobs if opp_jobs else (jobs if has_job else []), n_job_evidence)

        # Per-opportunity automation_potential: use only this opportunity's evidence titles
        opp_evidence_titles = " ".join(e.title for e in evidence_list)
        automation = _automation_potential_from_tag(problem, opp_evidence_titles)

        # Confidence uses per-opportunity freshness and unique source count (not global window)
        confidence = _confidence_single(n_evidence, has_headline, has_job, avg_age_days, unique_sources_count)

        # Signal quality classification
        support_level = _classify_support_level(
            n_evidence, has_headline, has_job, avg_age_days, unique_sources_count, is_padded=False
        )

        ai_cat = _bottleneck_to_ai_category(problem, template)
        title_short = problem[:50] + ("..." if len(problem) > 50 else "")
        # Compute identity/decision fields first so brief and actions can use them
        opp_trend_key = _make_trend_key(problem, ai_cat, is_padded=False)
        opp_recommendation = _classify_recommendation(support_level, confidence, pain_score, False, avg_age_days)
        opp_type = _classify_opportunity_type(ai_cat)
        brief = _build_opportunity_brief(
            title=title_short,
            ai_category=ai_cat,
            pain_score=pain_score,
            evidence=evidence_list,
            industry=industry,
            avg_age_days=avg_age_days,
            unique_sources_count=unique_sources_count,
            support_level=support_level,
            recommendation=opp_recommendation,
        )
        actions = _build_suggested_actions(
            problem=problem,
            opportunity_type=opp_type,
            recommendation=opp_recommendation,
            support_level=support_level,
            trend_key=opp_trend_key,
        )
        opp_leads = _build_leads_for_opportunity(
            problem=problem,
            keywords=problem_to_keywords.get(problem, set()),
            headlines=headlines,
            jobs=jobs,
            evidence=evidence_list,
        )
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
                brief=brief,
                support_level=support_level,
                signal_age_days_avg=round(avg_age_days, 1) if avg_age_days is not None else None,
                unique_sources_count=unique_sources_count,
                is_padded=False,
                trend_key=opp_trend_key,
                recommendation=opp_recommendation,
                opportunity_type=opp_type,
                suggested_actions=actions,
                leads=opp_leads,
            )
        )

    # Pad to 5 using template bottlenecks not yet covered.
    # Padded opportunities are explicitly flagged: is_padded=True, support_level="weak".
    # Evidence is drawn from the nearest available real signals for traceability,
    # but these opportunities have NO direct keyword evidence backing them.
    bottleneck_list = list(keyword_to_bottleneck.values()) or [f"Market dynamics in {city}"]
    all_sources: list[tuple[str, str, Literal["headline", "job"]]] = []
    for h in headlines[:8]:
        all_sources.append((h.get("title") or "Headline", h.get("link") or "#", "headline"))
    for j in jobs[:8]:
        all_sources.append((j.get("title") or "Job", j.get("link") or "#", "job"))
    real_sources = [(t, lnk, src) for t, lnk, src in all_sources if lnk and lnk != "#"]

    used_problems = {o.problem for o in opportunities}
    idx = 0
    while len(opportunities) < 5 and idx < len(bottleneck_list) * 2:
        p = bottleneck_list[idx % len(bottleneck_list)]
        if p not in used_problems:
            used_problems.add(p)
            bn_keywords = bottleneck_to_keywords.get(p, set())
            ev: list[EvidenceItem] = []
            seen_ev_links: set[str] = set()
            # First pass: prefer signals that contain a keyword for this bottleneck
            pool = real_sources or all_sources
            for t, lnk, src in pool:
                if lnk in seen_ev_links:
                    continue
                if bn_keywords and any(kw in t.lower() for kw in bn_keywords):
                    ev.append(EvidenceItem(title=t, link=lnk, source=src))
                    seen_ev_links.add(lnk)
                    if len(ev) >= 2:
                        break
            # Second pass: fill to 2 with any real signals (general market context)
            if len(ev) < 2:
                for t, lnk, src in pool:
                    if lnk not in seen_ev_links:
                        ev.append(EvidenceItem(title=t, link=lnk, source=src))
                        seen_ev_links.add(lnk)
                        if len(ev) >= 2:
                            break
            # Last resort: placeholder (only if no real sources exist at all)
            if not ev:
                ev = [EvidenceItem(title=f"{industry} context", link="#", source="headline")]
            pad_title = p[:50] + ("..." if len(p) > 50 else "")
            pad_cat = _bottleneck_to_ai_category(p, template)
            opportunities.append(
                OpportunityItem(
                    title=pad_title,
                    problem=p,
                    ai_category=pad_cat,
                    evidence=ev,
                    pain_score=3.0,
                    automation_potential=5.0,
                    roi_signal=4.0,
                    confidence=0.3,
                    business_case=BusinessCase(
                        savings_range_annual="$30k–$120k",
                        assumptions=["Template-padded: limited direct evidence for this bottleneck"],
                    ),
                    score_breakdown=ScoreBreakdown(signal_frequency=1.0 / 3.0, source_diversity=1.0 / 3.0, job_role_density=1.0 / 3.0),
                    brief=_build_opportunity_brief(
                        title=pad_title,
                        ai_category=pad_cat,
                        pain_score=3.0,
                        evidence=ev,
                        industry=industry,
                        support_level="weak",
                    ),
                    support_level="weak",
                    signal_age_days_avg=None,
                    unique_sources_count=0,
                    is_padded=True,
                    trend_key=_make_trend_key(p, pad_cat, is_padded=True),
                    recommendation="deprioritize",
                    opportunity_type=_classify_opportunity_type(pad_cat),
                    suggested_actions=_build_suggested_actions(
                        problem=p,
                        opportunity_type=_classify_opportunity_type(pad_cat),
                        recommendation="deprioritize",
                        support_level="weak",
                    ),
                    leads=_build_leads_for_opportunity(
                        problem=p,
                        keywords=set(),
                        headlines=headlines,
                        jobs=jobs,
                        evidence=ev,
                    ),
                )
            )
        idx += 1

    # Ensure at least 5 opportunities with generic fallbacks (always padded)
    fallback_problems = [f"Market dynamics in {city}", f"{industry} operational challenges", "Regional demand and supply", "Cost and efficiency pressures", "Regulatory and compliance"]
    for fp in fallback_problems:
        if len(opportunities) >= 5:
            break
        if fp in used_problems:
            continue
        used_problems.add(fp)
        ev_fb: list[EvidenceItem] = []
        seen_fb: set[str] = set()
        pool = real_sources or all_sources
        for t, lnk, src in pool[:2]:
            if lnk not in seen_fb:
                ev_fb.append(EvidenceItem(title=t, link=lnk, source=src))
                seen_fb.add(lnk)
        if not ev_fb:
            ev_fb = [EvidenceItem(title=f"{industry} context", link="#", source="headline")]
        fb_cat = _bottleneck_to_ai_category(fp, template)
        opportunities.append(
            OpportunityItem(
                title=fp[:50],
                problem=fp,
                ai_category=fb_cat,
                evidence=ev_fb,
                pain_score=2.5,
                automation_potential=5.0,
                roi_signal=3.0,
                confidence=0.25,
                business_case=BusinessCase(
                    savings_range_annual="$30k–$100k",
                    assumptions=["Template-padded: limited direct evidence; industry template only"],
                ),
                score_breakdown=ScoreBreakdown(signal_frequency=1.0 / 3.0, source_diversity=1.0 / 3.0, job_role_density=1.0 / 3.0),
                brief=_build_opportunity_brief(
                    title=fp[:50],
                    ai_category=fb_cat,
                    pain_score=2.5,
                    evidence=ev_fb,
                    industry=industry,
                    support_level="weak",
                ),
                support_level="weak",
                signal_age_days_avg=None,
                unique_sources_count=0,
                is_padded=True,
                trend_key=_make_trend_key(fp, fb_cat, is_padded=True),
                recommendation="deprioritize",
                opportunity_type=_classify_opportunity_type(fb_cat),
                suggested_actions=_build_suggested_actions(
                    problem=fp,
                    opportunity_type=_classify_opportunity_type(fb_cat),
                    recommendation="deprioritize",
                    support_level="weak",
                ),
                leads=_build_leads_for_opportunity(
                    problem=fp,
                    keywords=set(),
                    headlines=headlines,
                    jobs=jobs,
                    evidence=ev_fb,
                ),
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
        headlines, jobs, industry, city, template, deterministic=deterministic
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
