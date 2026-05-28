"""Industry templates: default objectives, bottlenecks, and keyword maps."""

from __future__ import annotations

from dataclasses import dataclass

from marketscout.normalize import SUPPORTED_INDUSTRIES, normalize_industry  # noqa: F401 (re-exported for convenience)

# Allowed AI categories (must match brain strategy enum)
AI_CATEGORIES_ALLOWED = (
    "Market entry",
    "Growth and scale",
    "Cost reduction",
    "Risk mitigation",
    "Regulatory & permits",
    "Operational efficiency",
    "Partnership and M&A",
)


@dataclass(frozen=True)
class IndustryTemplate:
    """Template for an industry: objectives, bottlenecks, and keyword -> bottleneck mapping."""

    industry_name: str
    default_objectives: tuple[str, ...]
    common_bottlenecks: tuple[str, ...]
    ai_categories_allowed: tuple[str, ...]
    keyword_map: tuple[tuple[str, str], ...]  # (keyword, bottleneck_tag)

    def keyword_to_bottleneck(self) -> dict[str, str]:
        """Return dict mapping lowercase keyword -> bottleneck label."""
        return {k.lower(): v for k, v in self.keyword_map}


def _construction_template() -> IndustryTemplate:
    return IndustryTemplate(
        industry_name="Construction",
        default_objectives=(
            "Market entry",
            "Growth and scale",
            "Cost reduction",
            "Risk mitigation",
            "Partnership and M&A",
            "Operational efficiency",
        ),
        common_bottlenecks=(
            "Labor shortages and wage pressure",
            "Permitting and regulatory delays",
            "Material cost and availability",
            "Supply chain and logistics constraints",
            "Skills gap and workforce training",
            "Interest rate and financing uncertainty",
        ),
        ai_categories_allowed=AI_CATEGORIES_ALLOWED,
        keyword_map=(
            # Labor — field roles & crews
            ("labor", "Labor shortages and wage pressure"),
            ("shortage", "Labor shortages and wage pressure"),
            ("wage", "Labor shortages and wage pressure"),
            ("hiring", "Labor shortages and wage pressure"),
            ("worker", "Labor shortages and wage pressure"),
            ("labourer", "Labor shortages and wage pressure"),
            ("laborer", "Labor shortages and wage pressure"),
            ("foreman", "Labor shortages and wage pressure"),
            ("superintendent", "Labor shortages and wage pressure"),
            ("supervisor", "Labor shortages and wage pressure"),
            ("site supervisor", "Labor shortages and wage pressure"),
            ("crew", "Labor shortages and wage pressure"),
            ("trade", "Labor shortages and wage pressure"),
            ("residential", "Labor shortages and wage pressure"),
            ("commercial", "Labor shortages and wage pressure"),
            ("construction site", "Labor shortages and wage pressure"),
            ("site", "Labor shortages and wage pressure"),
            # Permitting / regulatory — titles & compliance vocabulary
            ("permits", "Permitting and regulatory delays"),
            ("permit", "Permitting and regulatory delays"),
            ("building permit", "Permitting and regulatory delays"),
            ("regulation", "Permitting and regulatory delays"),
            ("regulatory", "Permitting and regulatory delays"),
            ("code", "Permitting and regulatory delays"),
            ("building code", "Permitting and regulatory delays"),
            ("inspection", "Permitting and regulatory delays"),
            ("inspector", "Permitting and regulatory delays"),
            ("zoning", "Permitting and regulatory delays"),
            ("renovation", "Permitting and regulatory delays"),
            ("municipal", "Permitting and regulatory delays"),
            ("variance", "Permitting and regulatory delays"),
            ("compliance", "Permitting and regulatory delays"),
            # Materials & estimating
            ("material", "Material cost and availability"),
            ("materials", "Material cost and availability"),
            ("framing", "Material cost and availability"),
            ("concrete", "Material cost and availability"),
            ("lumber", "Material cost and availability"),
            ("steel", "Material cost and availability"),
            ("roofing", "Material cost and availability"),
            ("drywall", "Material cost and availability"),
            ("estimator", "Material cost and availability"),
            ("estimate", "Material cost and availability"),
            ("takeoff", "Material cost and availability"),
            ("costs", "Material cost and availability"),
            # Supply chain — coordination, subs, procurement
            ("supply chain", "Supply chain and logistics constraints"),
            ("logistics", "Supply chain and logistics constraints"),
            ("procurement", "Supply chain and logistics constraints"),
            ("delivery", "Supply chain and logistics constraints"),
            ("inventory", "Supply chain and logistics constraints"),
            ("subcontractor", "Supply chain and logistics constraints"),
            ("supplier", "Supply chain and logistics constraints"),
            ("vendor", "Supply chain and logistics constraints"),
            ("project manager", "Supply chain and logistics constraints"),
            ("scheduling", "Supply chain and logistics constraints"),
            # Trades & skills
            ("skill", "Skills gap and workforce training"),
            ("skilled", "Skills gap and workforce training"),
            ("apprentice", "Skills gap and workforce training"),
            ("journeyman", "Skills gap and workforce training"),
            ("carpenter", "Skills gap and workforce training"),
            ("electrician", "Skills gap and workforce training"),
            ("plumber", "Skills gap and workforce training"),
            ("hvac", "Skills gap and workforce training"),
            ("welder", "Skills gap and workforce training"),
            ("ironworker", "Skills gap and workforce training"),
            # Financing
            ("interest rate", "Interest rate and financing uncertainty"),
            ("mortgage", "Interest rate and financing uncertainty"),
            ("financing", "Interest rate and financing uncertainty"),
            ("loan", "Interest rate and financing uncertainty"),
            ("lending", "Interest rate and financing uncertainty"),
            ("rate", "Interest rate and financing uncertainty"),
            ("inflation", "Interest rate and financing uncertainty"),
            ("capex", "Interest rate and financing uncertainty"),
        ),
    )


def _retail_template() -> IndustryTemplate:
    return IndustryTemplate(
        industry_name="Retail",
        default_objectives=(
            "Market entry",
            "Growth and scale",
            "Cost reduction",
            "Risk mitigation",
            "Partnership and M&A",
            "Operational efficiency",
        ),
        common_bottlenecks=(
            "Labor shortages and wage pressure",
            "Supply chain and logistics constraints",
            "Consumer demand and seasonality",
            "Rent and occupancy costs",
            "Competition and margin pressure",
            "Technology and omnichannel",
        ),
        ai_categories_allowed=AI_CATEGORIES_ALLOWED,
        keyword_map=(
            ("labor", "Labor shortages and wage pressure"),
            ("supply chain", "Supply chain and logistics constraints"),
            ("demand", "Consumer demand and seasonality"),
            ("rent", "Rent and occupancy costs"),
            ("competition", "Competition and margin pressure"),
            ("omnichannel", "Technology and omnichannel"),
            ("ecommerce", "Technology and omnichannel"),
        ),
    )


def _real_estate_template() -> IndustryTemplate:
    return IndustryTemplate(
        industry_name="Real Estate",
        default_objectives=(
            "Market entry",
            "Growth and scale",
            "Cost reduction",
            "Risk mitigation",
            "Partnership and M&A",
            "Operational efficiency",
        ),
        common_bottlenecks=(
            "Housing affordability and supply",
            "Interest rate and financing uncertainty",
            "Regulatory and zoning changes",
            "Labor and construction costs",
            "Inventory and absorption",
            "Climate and sustainability compliance",
        ),
        ai_categories_allowed=AI_CATEGORIES_ALLOWED,
        keyword_map=(
            ("housing", "Housing affordability and supply"),
            ("affordability", "Housing affordability and supply"),
            ("rate", "Interest rate and financing uncertainty"),
            ("zoning", "Regulatory and zoning changes"),
            ("regulation", "Regulatory and zoning changes"),
            ("labor", "Labor and construction costs"),
            ("inventory", "Inventory and absorption"),
            ("climate", "Climate and sustainability compliance"),
        ),
    )


def _technology_template() -> IndustryTemplate:
    return IndustryTemplate(
        industry_name="Technology",
        default_objectives=(
            "Market entry",
            "Growth and scale",
            "Cost reduction",
            "Risk mitigation",
            "Partnership and M&A",
            "Operational efficiency",
        ),
        common_bottlenecks=(
            "Talent and hiring competition",
            "Funding and runway",
            "Regulatory and compliance",
            "Infrastructure and scaling",
            "Competition and differentiation",
            "Cybersecurity and risk",
        ),
        ai_categories_allowed=AI_CATEGORIES_ALLOWED,
        keyword_map=(
            ("talent", "Talent and hiring competition"),
            ("hiring", "Talent and hiring competition"),
            ("funding", "Funding and runway"),
            ("regulation", "Regulatory and compliance"),
            ("scale", "Infrastructure and scaling"),
            ("competition", "Competition and differentiation"),
            ("security", "Cybersecurity and risk"),
        ),
    )


def _healthcare_template() -> IndustryTemplate:
    return IndustryTemplate(
        industry_name="Healthcare",
        default_objectives=(
            "Market entry",
            "Growth and scale",
            "Cost reduction",
            "Risk mitigation",
            "Partnership and M&A",
            "Operational efficiency",
        ),
        common_bottlenecks=(
            "Staffing and labor shortages",
            "Technology adoption and digital health",
            "Regulatory and compliance pressure",
            "Patient demand and capacity",
            "Cost and reimbursement pressure",
        ),
        ai_categories_allowed=AI_CATEGORIES_ALLOWED,
        keyword_map=(
            # Staffing and labor shortages — clinical roles and workforce gaps
            ("nurse", "Staffing and labor shortages"),
            ("physician", "Staffing and labor shortages"),
            ("doctor", "Staffing and labor shortages"),
            ("therapist", "Staffing and labor shortages"),
            ("technician", "Staffing and labor shortages"),
            ("hiring", "Staffing and labor shortages"),
            ("shortage", "Staffing and labor shortages"),
            ("vacancy", "Staffing and labor shortages"),
            ("recruitment", "Staffing and labor shortages"),
            ("staff", "Staffing and labor shortages"),
            ("staffing", "Staffing and labor shortages"),
            ("caregiver", "Staffing and labor shortages"),
            ("aide", "Staffing and labor shortages"),
            ("healthcare worker", "Staffing and labor shortages"),
            ("paramedic", "Staffing and labor shortages"),
            ("pharmacist", "Staffing and labor shortages"),
            ("turnover", "Staffing and labor shortages"),
            ("retention", "Staffing and labor shortages"),
            ("labor", "Staffing and labor shortages"),
            ("labour", "Staffing and labor shortages"),
            # Technology adoption and digital health — EHR, telehealth, AI
            ("ehr", "Technology adoption and digital health"),
            ("emr", "Technology adoption and digital health"),
            ("electronic health", "Technology adoption and digital health"),
            ("digital", "Technology adoption and digital health"),
            ("software", "Technology adoption and digital health"),
            ("telehealth", "Technology adoption and digital health"),
            ("telemedicine", "Technology adoption and digital health"),
            ("ai", "Technology adoption and digital health"),
            ("automation", "Technology adoption and digital health"),
            ("system", "Technology adoption and digital health"),
            ("platform", "Technology adoption and digital health"),
            ("integration", "Technology adoption and digital health"),
            ("data", "Technology adoption and digital health"),
            # Regulatory and compliance pressure — accreditation, licensing, privacy
            ("compliance", "Regulatory and compliance pressure"),
            ("regulation", "Regulatory and compliance pressure"),
            ("regulatory", "Regulatory and compliance pressure"),
            ("accreditation", "Regulatory and compliance pressure"),
            ("licensing", "Regulatory and compliance pressure"),
            ("privacy", "Regulatory and compliance pressure"),
            ("hipaa", "Regulatory and compliance pressure"),
            ("audit", "Regulatory and compliance pressure"),
            ("policy", "Regulatory and compliance pressure"),
            ("standard", "Regulatory and compliance pressure"),
            ("certification", "Regulatory and compliance pressure"),
            # Patient demand and capacity — volumes, access, surge
            ("patient", "Patient demand and capacity"),
            ("demand", "Patient demand and capacity"),
            ("capacity", "Patient demand and capacity"),
            ("waitlist", "Patient demand and capacity"),
            ("emergency", "Patient demand and capacity"),
            ("surge", "Patient demand and capacity"),
            ("bed", "Patient demand and capacity"),
            ("clinic", "Patient demand and capacity"),
            ("care", "Patient demand and capacity"),
            ("treatment", "Patient demand and capacity"),
            ("volume", "Patient demand and capacity"),
            # Cost and reimbursement pressure — budgets, funding, billing
            ("cost", "Cost and reimbursement pressure"),
            ("budget", "Cost and reimbursement pressure"),
            ("funding", "Cost and reimbursement pressure"),
            ("reimbursement", "Cost and reimbursement pressure"),
            ("insurance", "Cost and reimbursement pressure"),
            ("billing", "Cost and reimbursement pressure"),
            ("revenue", "Cost and reimbursement pressure"),
            ("expense", "Cost and reimbursement pressure"),
            ("cut", "Cost and reimbursement pressure"),
            ("reduction", "Cost and reimbursement pressure"),
        ),
    )


def _manufacturing_template() -> IndustryTemplate:
    return IndustryTemplate(
        industry_name="Manufacturing",
        default_objectives=(
            "Market entry",
            "Growth and scale",
            "Cost reduction",
            "Risk mitigation",
            "Partnership and M&A",
            "Operational efficiency",
        ),
        common_bottlenecks=(
            "Labor shortages and wage pressure",
            "Supply chain and logistics constraints",
            "Material cost and availability",
            "Energy costs and transition",
            "Skills gap and workforce training",
            "Regulatory and environmental compliance",
        ),
        ai_categories_allowed=AI_CATEGORIES_ALLOWED,
        keyword_map=(
            ("labor", "Labor shortages and wage pressure"),
            ("supply chain", "Supply chain and logistics constraints"),
            ("material", "Material cost and availability"),
            ("energy", "Energy costs and transition"),
            ("skill", "Skills gap and workforce training"),
            ("regulation", "Regulatory and environmental compliance"),
        ),
    )


def _professional_services_template() -> IndustryTemplate:
    return IndustryTemplate(
        industry_name="Professional Services",
        default_objectives=(
            "Market entry",
            "Growth and scale",
            "Cost reduction",
            "Risk mitigation",
            "Partnership and M&A",
            "Operational efficiency",
        ),
        common_bottlenecks=(
            "Talent retention and hiring",
            "Client demand and pipeline",
            "Pricing and margin pressure",
            "Regulatory and compliance",
            "Technology and delivery",
            "Competition and differentiation",
        ),
        ai_categories_allowed=AI_CATEGORIES_ALLOWED,
        keyword_map=(
            ("talent", "Talent retention and hiring"),
            ("hiring", "Talent retention and hiring"),
            ("pipeline", "Client demand and pipeline"),
            ("pricing", "Pricing and margin pressure"),
            ("regulation", "Regulatory and compliance"),
            ("competition", "Competition and differentiation"),
        ),
    )


def _security_template() -> IndustryTemplate:
    return IndustryTemplate(
        industry_name="Security",
        default_objectives=(
            "Market entry",
            "Growth and scale",
            "Cost reduction",
            "Risk mitigation",
            "Partnership and M&A",
            "Operational efficiency",
        ),
        common_bottlenecks=(
            "Workforce shortages and retention",
            "Technology and automation gaps",
            "Compliance and licensing pressure",
            "Contract and client acquisition",
            "Insurance and liability concerns",
        ),
        ai_categories_allowed=AI_CATEGORIES_ALLOWED,
        keyword_map=(
            # Workforce shortages and retention — guards, officers, dispatch, recruiting
            ("guard", "Workforce shortages and retention"),
            ("officer", "Workforce shortages and retention"),
            ("security officer", "Workforce shortages and retention"),
            ("patrol", "Workforce shortages and retention"),
            ("armed", "Workforce shortages and retention"),
            ("unarmed", "Workforce shortages and retention"),
            ("dispatcher", "Workforce shortages and retention"),
            ("surveillance", "Workforce shortages and retention"),
            ("screening", "Workforce shortages and retention"),
            ("hiring", "Workforce shortages and retention"),
            ("shortage", "Workforce shortages and retention"),
            ("retention", "Workforce shortages and retention"),
            ("turnover", "Workforce shortages and retention"),
            ("recruitment", "Workforce shortages and retention"),
            # Technology and automation gaps — cameras, access, biometrics, integration
            ("cctv", "Technology and automation gaps"),
            ("camera", "Technology and automation gaps"),
            ("access control", "Technology and automation gaps"),
            ("biometric", "Technology and automation gaps"),
            ("monitoring", "Technology and automation gaps"),
            ("software", "Technology and automation gaps"),
            ("integration", "Technology and automation gaps"),
            ("cyber", "Technology and automation gaps"),
            ("technology", "Technology and automation gaps"),
            ("system", "Technology and automation gaps"),
            ("upgrade", "Technology and automation gaps"),
            # Compliance and licensing pressure — credentials, regulation, vetting
            ("license", "Compliance and licensing pressure"),
            ("licensed", "Compliance and licensing pressure"),
            ("certification", "Compliance and licensing pressure"),
            ("compliant", "Compliance and licensing pressure"),
            ("regulatory", "Compliance and licensing pressure"),
            ("permit", "Compliance and licensing pressure"),
            ("background check", "Compliance and licensing pressure"),
            ("clearance", "Compliance and licensing pressure"),
            ("training", "Compliance and licensing pressure"),
            # Contract and client acquisition — sales channels and verticals
            ("contract", "Contract and client acquisition"),
            ("client", "Contract and client acquisition"),
            ("bid", "Contract and client acquisition"),
            ("proposal", "Contract and client acquisition"),
            ("corporate", "Contract and client acquisition"),
            ("government", "Contract and client acquisition"),
            ("retail", "Contract and client acquisition"),
            ("commercial", "Contract and client acquisition"),
            ("residential", "Contract and client acquisition"),
            # Insurance and liability concerns — risk transfer and incidents
            ("insurance", "Insurance and liability concerns"),
            ("liability", "Insurance and liability concerns"),
            ("incident", "Insurance and liability concerns"),
            ("claim", "Insurance and liability concerns"),
            ("risk", "Insurance and liability concerns"),
            ("coverage", "Insurance and liability concerns"),
            ("bonded", "Insurance and liability concerns"),
        ),
    )


INDUSTRY_TEMPLATES: dict[str, IndustryTemplate] = {
    "Construction": _construction_template(),
    "Retail": _retail_template(),
    "Real Estate": _real_estate_template(),
    "Technology": _technology_template(),
    "Healthcare": _healthcare_template(),
    "Manufacturing": _manufacturing_template(),
    "Professional Services": _professional_services_template(),
    "Security": _security_template(),
}


def _dynamic_template(industry_name: str) -> IndustryTemplate:
    """
    Build a generic but useful template for any industry not in INDUSTRY_TEMPLATES.

    Uses broad cross-industry keywords so the scoring pipeline still extracts
    meaningful signals (hiring pressure, cost, compliance, technology, competition)
    regardless of what the user typed.  The raw ``industry_name`` is preserved as
    the ``industry_name`` field so it flows through to reports correctly.
    """
    label = industry_name.strip().title() if industry_name.strip() else "General"
    return IndustryTemplate(
        industry_name=label,
        default_objectives=(
            "Market entry",
            "Growth and scale",
            "Cost reduction",
            "Risk mitigation",
            "Operational efficiency",
        ),
        common_bottlenecks=(
            "Workforce and hiring pressure",
            "Technology and automation gaps",
            "Regulatory and compliance pressure",
            "Cost and operational efficiency",
            "Market competition and differentiation",
        ),
        ai_categories_allowed=AI_CATEGORIES_ALLOWED,
        keyword_map=(
            # Workforce and hiring pressure
            ("hiring", "Workforce and hiring pressure"),
            ("shortage", "Workforce and hiring pressure"),
            ("recruitment", "Workforce and hiring pressure"),
            ("turnover", "Workforce and hiring pressure"),
            ("retention", "Workforce and hiring pressure"),
            ("staffing", "Workforce and hiring pressure"),
            ("talent", "Workforce and hiring pressure"),
            ("workforce", "Workforce and hiring pressure"),
            ("worker", "Workforce and hiring pressure"),
            ("labour", "Workforce and hiring pressure"),
            ("labor", "Workforce and hiring pressure"),
            ("wage", "Workforce and hiring pressure"),
            ("salary", "Workforce and hiring pressure"),
            # Technology and automation gaps
            ("technology", "Technology and automation gaps"),
            ("software", "Technology and automation gaps"),
            ("automation", "Technology and automation gaps"),
            ("digital", "Technology and automation gaps"),
            ("system", "Technology and automation gaps"),
            ("platform", "Technology and automation gaps"),
            ("upgrade", "Technology and automation gaps"),
            ("integration", "Technology and automation gaps"),
            ("cyber", "Technology and automation gaps"),
            ("data", "Technology and automation gaps"),
            ("ai", "Technology and automation gaps"),
            # Regulatory and compliance pressure
            ("regulation", "Regulatory and compliance pressure"),
            ("regulatory", "Regulatory and compliance pressure"),
            ("compliance", "Regulatory and compliance pressure"),
            ("license", "Regulatory and compliance pressure"),
            ("certification", "Regulatory and compliance pressure"),
            ("permit", "Regulatory and compliance pressure"),
            ("inspection", "Regulatory and compliance pressure"),
            ("audit", "Regulatory and compliance pressure"),
            ("training", "Regulatory and compliance pressure"),
            # Cost and operational efficiency
            ("cost", "Cost and operational efficiency"),
            ("costs", "Cost and operational efficiency"),
            ("efficiency", "Cost and operational efficiency"),
            ("overhead", "Cost and operational efficiency"),
            ("budget", "Cost and operational efficiency"),
            ("pricing", "Cost and operational efficiency"),
            ("inflation", "Cost and operational efficiency"),
            ("supply chain", "Cost and operational efficiency"),
            ("logistics", "Cost and operational efficiency"),
            ("procurement", "Cost and operational efficiency"),
            # Market competition and differentiation
            ("competition", "Market competition and differentiation"),
            ("competitor", "Market competition and differentiation"),
            ("market", "Market competition and differentiation"),
            ("growth", "Market competition and differentiation"),
            ("expansion", "Market competition and differentiation"),
            ("contract", "Market competition and differentiation"),
            ("client", "Market competition and differentiation"),
            ("customer", "Market competition and differentiation"),
            ("demand", "Market competition and differentiation"),
            ("revenue", "Market competition and differentiation"),
        ),
    )


def get_template(industry_name: str) -> IndustryTemplate:
    """
    Return the IndustryTemplate for the given industry name.

    Accepts any case and common aliases via normalize_industry (e.g. "tech" → Technology).
    For unrecognised inputs, returns a dynamic cross-industry template built from
    the raw input string rather than silently falling back to Construction.

    Note: the CLI validates industries via _validate_and_normalize before this is ever
    called in the run path, so dynamic templates are only reached by direct callers
    (e.g. the web API, which accepts free-text industry input).
    """
    canonical = normalize_industry(industry_name)
    if canonical:
        return INDUSTRY_TEMPLATES.get(canonical, _dynamic_template(industry_name))
    return _dynamic_template(industry_name)
