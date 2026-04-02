"""Brain schema — compatibility shim. Implementation lives in marketscout.backend.schema."""

from marketscout.backend.schema import (
    STRATEGY_VERSION,
    AI_CATEGORIES,
    EvidenceItem,
    BusinessCase,
    ScoreBreakdown,
    OpportunityBrief,
    Lead,
    OpportunityItem,
    SignalsUsed,
    DataQuality,
    StrategyOutput,
    get_json_schema,
)

__all__ = [
    "STRATEGY_VERSION",
    "AI_CATEGORIES",
    "EvidenceItem",
    "BusinessCase",
    "ScoreBreakdown",
    "OpportunityBrief",
    "Lead",
    "OpportunityItem",
    "SignalsUsed",
    "DataQuality",
    "StrategyOutput",
    "get_json_schema",
]
