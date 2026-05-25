"""Input normalization helpers for city and industry strings."""

from __future__ import annotations

import re

# Matches a trailing two-letter ALL-CAPS postal/province/state code,
# optionally preceded by a comma (e.g. ", BC", " ON", ",CA").
# Deliberately restricted to exactly two uppercase letters so city-name words
# like "York" (4 chars) or "New" are never stripped.
_POSTAL_SUFFIX_RE = re.compile(r",?\s+[A-Z]{2}$")


def normalize_city(city: str) -> str:
    """
    Normalize a city string for display and cache-key use.

    Steps:
    1. Strip leading/trailing whitespace.
    2. Collapse internal runs of whitespace to a single space.
    3. Strip trailing postal/region suffixes like ", BC", ", ON", ", CA", ", NY".
    4. Title-case the result.

    Examples:
        "Vancouver, BC"     → "Vancouver"
        "  new   york  "    → "New York"
        "TORONTO, ON"       → "Toronto"
        "London, UK"        → "London"
        "san francisco, ca" → "San Francisco"
        "Calgary"           → "Calgary"
    """
    city = " ".join(city.strip().split())
    # Strip two-letter postal/province/state codes (e.g. "Vancouver, BC" → "Vancouver").
    city = _POSTAL_SUFFIX_RE.sub("", city).strip()
    # Strip anything after a remaining comma (e.g. "Paris, France" → "Paris").
    if "," in city:
        city = city.split(",")[0].strip()
    return city.title()


# ---------------------------------------------------------------------------
# Industry normalization
# ---------------------------------------------------------------------------

# Canonical industry names (single source of truth — also imported by industries.py).
SUPPORTED_INDUSTRIES: tuple[str, ...] = (
    "Construction",
    "Healthcare",
    "Manufacturing",
    "Professional Services",
    "Real Estate",
    "Retail",
    "Security",
    "Technology",
)

# Aliases: normalized-lowercase input → canonical name.
# Keys are already lower-stripped; values are canonical.
_INDUSTRY_ALIASES: dict[str, str] = {
    # ── Construction ──────────────────────────────────────────────────────────
    "construction": "Construction",
    "building": "Construction",
    "building construction": "Construction",
    "contractor": "Construction",
    "contractors": "Construction",
    "general contractor": "Construction",
    "general contracting": "Construction",
    "civil construction": "Construction",
    "civil engineering": "Construction",
    "residential construction": "Construction",
    "commercial construction": "Construction",
    "home building": "Construction",
    "renovation": "Construction",
    "renovations": "Construction",
    "trades": "Construction",
    # ── Healthcare ────────────────────────────────────────────────────────────
    "healthcare": "Healthcare",
    "health care": "Healthcare",
    "health": "Healthcare",
    "medical": "Healthcare",
    "hospital": "Healthcare",
    "hospitals": "Healthcare",
    "nursing": "Healthcare",
    "nurse": "Healthcare",
    "pharma": "Healthcare",
    "pharmaceutical": "Healthcare",
    "pharmaceuticals": "Healthcare",
    "clinic": "Healthcare",
    "clinics": "Healthcare",
    "dental": "Healthcare",
    "dentistry": "Healthcare",
    "mental health": "Healthcare",
    "homecare": "Healthcare",
    "home care": "Healthcare",
    "long-term care": "Healthcare",
    "long term care": "Healthcare",
    "physiotherapy": "Healthcare",
    "pharmacy": "Healthcare",
    # ── Manufacturing ─────────────────────────────────────────────────────────
    "manufacturing": "Manufacturing",
    "mfg": "Manufacturing",
    "production": "Manufacturing",
    "factory": "Manufacturing",
    "factories": "Manufacturing",
    "industrial": "Manufacturing",
    "assembly": "Manufacturing",
    "fabrication": "Manufacturing",
    "machining": "Manufacturing",
    "plant operations": "Manufacturing",
    # ── Professional Services ─────────────────────────────────────────────────
    "professional services": "Professional Services",
    "professional service": "Professional Services",
    "prof services": "Professional Services",
    "consulting": "Professional Services",
    "consultancy": "Professional Services",
    "advisory": "Professional Services",
    "accounting": "Professional Services",
    "legal": "Professional Services",
    "legal services": "Professional Services",
    "law": "Professional Services",
    "hr": "Professional Services",
    "human resources": "Professional Services",
    "staffing": "Professional Services",
    "recruitment": "Professional Services",
    "marketing": "Professional Services",
    "advertising": "Professional Services",
    "pr": "Professional Services",
    "public relations": "Professional Services",
    "finance": "Professional Services",
    "financial services": "Professional Services",
    # ── Real Estate ───────────────────────────────────────────────────────────
    "real estate": "Real Estate",
    "realestate": "Real Estate",
    "property": "Real Estate",
    "property management": "Real Estate",
    "realty": "Real Estate",
    "residential real estate": "Real Estate",
    "commercial real estate": "Real Estate",
    "leasing": "Real Estate",
    "land development": "Real Estate",
    "housing": "Real Estate",
    # ── Retail ────────────────────────────────────────────────────────────────
    "retail": "Retail",
    "ecommerce": "Retail",
    "e-commerce": "Retail",
    "online retail": "Retail",
    "grocery": "Retail",
    "food retail": "Retail",
    "fashion": "Retail",
    "apparel": "Retail",
    "consumer goods": "Retail",
    "cpg": "Retail",
    # ── Security ─────────────────────────────────────────────────────────────
    "security": "Security",
    "security services": "Security",
    "physical security": "Security",
    "guard services": "Security",
    "private security": "Security",
    "security guard": "Security",
    "security guards": "Security",
    "guards": "Security",
    "loss prevention": "Security",
    "protective services": "Security",
    "corporate security": "Security",
    "event security": "Security",
    "facility security": "Security",
    # ── Technology ────────────────────────────────────────────────────────────
    "technology": "Technology",
    "tech": "Technology",
    "software": "Technology",
    "software development": "Technology",
    "software engineering": "Technology",
    "it": "Technology",
    "information technology": "Technology",
    "saas": "Technology",
    "cloud": "Technology",
    "cloud computing": "Technology",
    "cybersecurity": "Technology",
    "cyber security": "Technology",
    "data": "Technology",
    "data science": "Technology",
    "ai": "Technology",
    "artificial intelligence": "Technology",
    "machine learning": "Technology",
    "fintech": "Technology",
    "edtech": "Technology",
    "healthtech": "Technology",
    "startup": "Technology",
    "startups": "Technology",
    "dev": "Technology",
    "devops": "Technology",
    "mobile": "Technology",
    "app development": "Technology",
}

# Also add exact canonical names (case-insensitive) as valid aliases.
for _canonical in SUPPORTED_INDUSTRIES:
    _INDUSTRY_ALIASES.setdefault(_canonical.lower(), _canonical)


def normalize_industry(industry: str) -> str | None:
    """
    Normalize an industry string to a canonical name.

    Returns the canonical industry name string, or None if unrecognised.

    Examples:
        "construction"           → "Construction"
        "RETAIL"                 → "Retail"
        "  real estate  "        → "Real Estate"
        "tech"                   → "Technology"
        "health care"            → "Healthcare"
        "unknown industry"       → None
    """
    key = " ".join(industry.strip().split()).lower()
    return _INDUSTRY_ALIASES.get(key)
