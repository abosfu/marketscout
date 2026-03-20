"""Strategy output schema: Pydantic models and JSON schema for validated output (v2.0)."""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, model_validator

STRATEGY_VERSION = "2.0"

# AI category enum for opportunity mapping
AI_CATEGORIES = (
    "Market entry",
    "Growth and scale",
    "Cost reduction",
    "Risk mitigation",
    "Regulatory & permits",
    "Operational efficiency",
    "Partnership and M&A",
)


class EvidenceItem(BaseModel):
    """Single evidence item (headline or job) supporting an opportunity."""

    title: str = Field(..., description="Headline or job title text")
    link: str = Field(..., description="URL to source")
    source: Literal["headline", "job"] = Field(..., description="Whether from headline or job listing")


class BusinessCase(BaseModel):
    """Business incentive estimates for an opportunity."""

    savings_range_annual: str = Field(..., description="e.g. '$80k–$250k'")
    assumptions: list[str] = Field(default_factory=list, description="Key assumptions")


class ScoreBreakdown(BaseModel):
    """Explainable scoring weights per opportunity; must sum to 1.0."""

    signal_frequency: float = Field(..., ge=0.0, le=1.0, description="Weight from evidence/signal frequency")
    source_diversity: float = Field(..., ge=0.0, le=1.0, description="Weight from headline+job mix")
    job_role_density: float = Field(..., ge=0.0, le=1.0, description="Weight from job listing density")

    @model_validator(mode="after")
    def check_sum_to_one(self) -> "ScoreBreakdown":
        total = self.signal_frequency + self.source_diversity + self.job_role_density
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"score_breakdown must sum to 1.0, got {total}")
        return self


class OpportunityBrief(BaseModel):
    """Actionable decision brief for a single opportunity."""

    likely_buyer: str = Field(..., description="Persona or role most likely to feel this pain")
    pain_theme: str = Field(..., description="Short label for the pain category")
    commercial_angle: str = Field(..., description="Type of product or service that addresses this")
    suggested_next_step: str = Field(..., description="Recommended action based on signal strength")
    why_now: str = Field(..., description="Evidence-based urgency signal for this opportunity")


class Lead(BaseModel):
    """A company identified as a potential sales target for a specific opportunity."""

    company_name: str = Field(..., description="Company or organisation name")
    reason: str = Field(..., description="Why this company is relevant to the opportunity")
    signal_type: Literal["job", "news"] = Field(
        ..., description="Type of signal that identified this company"
    )
    signal_reference: str = Field(
        ..., description="Short title or snippet from the source signal (≤80 chars)"
    )
    priority_score: float = Field(
        ..., ge=0.0, le=10.0, description="Heuristic relevance score 0–10"
    )


class OpportunityItem(BaseModel):
    """One opportunity with proof metrics, business case, and explainable score breakdown."""

    title: str = Field(..., description="Short opportunity title")
    problem: str = Field(..., description="Problem statement")
    ai_category: str = Field(..., description="AI match category from enum")
    evidence: list[EvidenceItem] = Field(
        ...,
        min_length=1,
        description="Evidence items from headlines/jobs (>=2 recommended)",
    )
    pain_score: float = Field(..., ge=0.0, le=10.0, description="Pain score 0–10")
    automation_potential: float = Field(..., ge=0.0, le=10.0, description="Automation potential 0–10")
    roi_signal: float = Field(..., ge=0.0, le=10.0, description="ROI signal strength 0–10")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence 0–1")
    business_case: BusinessCase = Field(..., description="Savings range and assumptions")
    score_breakdown: Optional[ScoreBreakdown] = Field(
        default=None,
        description="Explainable weights (signal_frequency, source_diversity, job_role_density) summing to 1.0",
    )
    brief: Optional[OpportunityBrief] = Field(
        default=None,
        description="Actionable decision brief: buyer, pain theme, commercial angle, next step, why now",
    )
    # ── Signal quality fields ───────────────────────────────────────────────
    support_level: Literal["strong", "moderate", "weak"] = Field(
        default="moderate",
        description=(
            "Signal quality classification: strong = well-evidenced and fresh; "
            "moderate = partial coverage or moderate recency; "
            "weak = thin evidence, stale signals, or template-padded"
        ),
    )
    signal_age_days_avg: Optional[float] = Field(
        default=None,
        ge=0.0,
        description="Average age of evidence signals in days; None if timestamps unavailable",
    )
    unique_sources_count: int = Field(
        default=0,
        ge=0,
        description="Count of unique publishers or companies represented in evidence",
    )
    is_padded: bool = Field(
        default=False,
        description="True if this opportunity was added via template padding (no direct keyword evidence)",
    )
    # ── Identity and actionability fields ──────────────────────────────────
    trend_key: str = Field(
        default="",
        description=(
            "Stable canonical identifier for cross-run opportunity tracking. "
            "Format: '{category_slug}::{problem_slug}' for real opportunities; "
            "'padded::{problem_slug}' for template-padded ones. "
            "City-agnostic and truncation-proof."
        ),
    )
    recommendation: Literal["pursue_now", "monitor", "validate_further", "deprioritize"] = Field(
        default="monitor",
        description=(
            "Rule-based decision recommendation integrating support_level, confidence, "
            "pain_score, freshness, and padding. "
            "pursue_now = act immediately; monitor = watch across runs; "
            "validate_further = needs more evidence; deprioritize = discard."
        ),
    )
    opportunity_type: Literal["operational", "strategic", "compliance"] = Field(
        default="operational",
        description=(
            "Opportunity classification derived from ai_category. "
            "operational = day-to-day pain (ops buyer, short cycle); "
            "strategic = long-horizon initiative (exec buyer); "
            "compliance = regulatory/legal mandate (legal/finance buyer)."
        ),
    )
    suggested_actions: list[str] = Field(
        default_factory=list,
        description=(
            "Ordered list of 1–3 specific, actionable next steps. "
            "Derived from recommendation, opportunity_type, support_level, and problem text. "
            "Rule-based and deterministic — no LLM required."
        ),
    )
    leads: list[Lead] = Field(
        default_factory=list,
        description=(
            "Top 3–5 companies identified as potential sales targets for this opportunity. "
            "Extracted from job and news signals via keyword matching. "
            "Ranked by signal strength (job > news) and frequency."
        ),
    )


class SignalsUsed(BaseModel):
    """Counts of signals used to build the strategy (v2.0)."""

    headlines_count: int = Field(..., ge=0, description="Number of headlines used")
    jobs_count: int = Field(0, ge=0, description="Number of job listings used")
    news_sources_count: int = Field(0, ge=0, description="Distinct news/headline sources")
    job_companies_count: int = Field(0, ge=0, description="Distinct job employers/sources")


class DataQuality(BaseModel):
    """Data quality metrics for the strategy."""

    freshness_window_days: int = Field(..., ge=0, description="Age of newest vs oldest signal in days")
    coverage_score: float = Field(..., ge=0.0, le=1.0, description="Coverage score 0–1")
    source_mix_score: float = Field(..., ge=0.0, le=1.0, description="Source diversity score 0–1")


class StrategyOutput(BaseModel):
    """Full strategy output: schema-validated JSON (v2.0). Opportunity Map first-class."""

    strategy_version: Literal["2.0"] = Field(
        default=STRATEGY_VERSION,
        description="Schema version for strategy output",
    )
    city: str = Field(..., description="City for the analysis")
    industry: str = Field(..., description="Industry for the analysis")
    opportunity_map: list[OpportunityItem] = Field(
        ...,
        min_length=5,
        max_length=8,
        description="5–8 opportunities with evidence and business case",
    )
    signals_used: SignalsUsed = Field(..., description="Counts of signals used")
    data_quality: DataQuality = Field(..., description="Freshness, coverage, and source mix")

    def to_json_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dict (for download / API)."""
        return self.model_dump(mode="json")


def get_json_schema() -> dict[str, Any]:
    """Return JSON Schema dict for StrategyOutput (for LLM or validation)."""
    return StrategyOutput.model_json_schema()
