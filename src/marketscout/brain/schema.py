"""Strategy output schema: Pydantic models and JSON schema for validated output."""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

STRATEGY_VERSION = "1.1"


class SignalsUsed(BaseModel):
    """Counts of signals used to build the strategy."""

    headlines_count: int = Field(..., ge=0, description="Number of headlines used")
    jobs_count: int = Field(0, ge=0, description="Number of job listings used")
    econ_used: bool = Field(False, description="Whether economic data was used")


class ScoreBreakdown(BaseModel):
    """Multi-signal pain score breakdown."""

    news_signal_score: int = Field(..., ge=0, le=10, description="Score from headlines (0-10)")
    jobs_signal_score: int = Field(0, ge=0, le=10, description="Score from jobs (0-10)")
    combined_pain_score: int = Field(..., ge=1, le=10, description="Weighted combined score (1-10)")
    weights: dict[str, float] = Field(
        default_factory=lambda: {"news": 0.6, "jobs": 0.4},
        description="Weights used for combination",
    )


class ProblemEvidence(BaseModel):
    """A single problem with supporting headline or job evidence."""

    problem: str = Field(..., description="Short problem description")
    evidence_headline: str = Field(..., description="Headline or job title supporting this problem")
    evidence_link: str = Field(..., description="URL to source")
    evidence_source: Optional[Literal["headline", "job"]] = Field(
        None,
        description="Whether evidence is from a headline or a job listing",
    )


class AIMatch(BaseModel):
    """AI-derived match category and recommended approach."""

    category: str = Field(..., description="Match category label")
    recommended_approach: str = Field(..., description="Recommended strategy approach")


class PlanPhase(BaseModel):
    """Single phase of the 30/60/90 plan."""

    phase: str = Field(..., description="e.g. 30-day, 60-day, 90-day")
    actions: list[str] = Field(..., description="List of actionable items")


class ROINotes(BaseModel):
    """ROI assumptions and ranges."""

    ranges: str = Field(..., description="Expected ROI range or band")
    assumptions: list[str] = Field(..., description="Key assumptions behind the range")


class StrategyOutput(BaseModel):
    """Full strategy output: schema-validated JSON for the dashboard (v1.1)."""

    strategy_version: Literal["1.0", "1.1"] = Field(
        default=STRATEGY_VERSION,
        description="Schema version for strategy output",
    )
    pain_score: int = Field(..., ge=1, le=10, description="Combined pain score 1-10 (legacy; same as score_breakdown.combined_pain_score)")
    signals_used: Optional[SignalsUsed] = Field(None, description="Counts of signals used (v1.1)")
    score_breakdown: Optional[ScoreBreakdown] = Field(None, description="Multi-signal score breakdown (v1.1)")
    problems: list[ProblemEvidence] = Field(
        ...,
        min_length=4,
        max_length=6,
        description="4-6 problems with evidence from headlines and/or jobs",
    )
    ai_matches: list[AIMatch] = Field(
        ...,
        min_length=1,
        description="AI match categories and recommended approaches",
    )
    plan_30_60_90: list[PlanPhase] = Field(
        ...,
        min_length=3,
        max_length=3,
        description="30, 60, 90 day plan phases",
    )
    roi_notes: ROINotes = Field(..., description="ROI ranges and assumptions")

    def to_json_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dict (for download / API)."""
        return self.model_dump(mode="json")


def get_json_schema() -> dict[str, Any]:
    """Return JSON Schema dict for StrategyOutput (for LLM or validation)."""
    return StrategyOutput.model_json_schema()
