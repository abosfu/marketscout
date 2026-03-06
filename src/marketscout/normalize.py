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
    "Technology",
)

# Aliases: normalized-lowercase input → canonical name.
# Keys are already lower-stripped; values are canonical.
_INDUSTRY_ALIASES: dict[str, str] = {
    # Construction
    "construction": "Construction",
    # Healthcare
    "healthcare": "Healthcare",
    "health care": "Healthcare",
    "health": "Healthcare",
    "medical": "Healthcare",
    # Manufacturing
    "manufacturing": "Manufacturing",
    "mfg": "Manufacturing",
    # Professional Services
    "professional services": "Professional Services",
    "professional service": "Professional Services",
    "prof services": "Professional Services",
    "consulting": "Professional Services",
    # Real Estate
    "real estate": "Real Estate",
    "realestate": "Real Estate",
    "property": "Real Estate",
    # Retail
    "retail": "Retail",
    # Technology
    "technology": "Technology",
    "tech": "Technology",
    "software": "Technology",
    "it": "Technology",
    "information technology": "Technology",
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
