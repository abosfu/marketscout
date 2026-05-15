"""Industry templates: default objectives, bottlenecks, and keyword maps."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

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
            "Regulatory and compliance",
            "Cost and reimbursement pressure",
            "Technology adoption",
            "Patient access and demand",
            "Supply chain and procurement",
        ),
        ai_categories_allowed=AI_CATEGORIES_ALLOWED,
        keyword_map=(
            ("staff", "Staffing and labor shortages"),
            ("labor", "Staffing and labor shortages"),
            ("regulation", "Regulatory and compliance"),
            ("reimbursement", "Cost and reimbursement pressure"),
            ("technology", "Technology adoption"),
            ("supply chain", "Supply chain and procurement"),
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


INDUSTRY_TEMPLATES: dict[str, IndustryTemplate] = {
    "Construction": _construction_template(),
    "Retail": _retail_template(),
    "Real Estate": _real_estate_template(),
    "Technology": _technology_template(),
    "Healthcare": _healthcare_template(),
    "Manufacturing": _manufacturing_template(),
    "Professional Services": _professional_services_template(),
}


def get_template(industry_name: str) -> IndustryTemplate:
    """
    Return the IndustryTemplate for the given industry name.

    Accepts any case and common aliases via normalize_industry (e.g. "tech" → Technology).
    Falls back to Construction for unrecognised inputs so the pipeline always has a template.
    Note: the CLI validates industries via _validate_and_normalize before this is ever called
    in the run path, so the fallback is only reached by direct callers (e.g. unit tests).
    """
    canonical = normalize_industry(industry_name)
    return INDUSTRY_TEMPLATES.get(canonical or "", _construction_template())
