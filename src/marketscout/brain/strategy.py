"""Brain strategy — compatibility shim. Implementation lives in marketscout.backend.ai.strategy."""

from marketscout.backend.ai.strategy import (
    # Public API
    generate_strategy,
    generate_mock_strategy,
    build_signal_analysis,
    _call_openai_for_strategy,
    # Private functions accessed by tests
    _build_suggested_actions,
    _build_opportunity_brief,
    _build_leads_for_opportunity,
    _build_problem_specific_commercial_angle,
    _extract_company_from_headline,
    _classify_opportunity_type,
    _classify_recommendation,
    _classify_support_level,
    _confidence_single,
    _freshness_bucket,
    _make_trend_key,
    _signal_age_days,
    _slugify,
    # Constants also used by tests
    JOBS_MANUAL_OPS_KEYWORDS,
    HIGH_AUTOMATION_KEYWORDS,
    LOW_AUTOMATION_KEYWORDS,
)
