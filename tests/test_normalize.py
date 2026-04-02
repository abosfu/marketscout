"""Input normalization tests: city, industry, template lookup, and CLI validation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from marketscout.normalize import SUPPORTED_INDUSTRIES, normalize_city, normalize_industry
import marketscout.scout.headlines as _ms_headlines
import marketscout.scout.providers.rss as _ms_rss
from marketscout.templates.industries import get_template


# ── normalize_city ────────────────────────────────────────────────────────────

class TestNormalizeCity:
    def test_strips_whitespace(self):
        assert normalize_city("  Vancouver  ") == "Vancouver"

    def test_collapses_internal_whitespace(self):
        assert normalize_city("New   York") == "New York"

    def test_strips_two_letter_province_suffix(self):
        assert normalize_city("Vancouver, BC") == "Vancouver"

    def test_strips_two_letter_state_suffix(self):
        assert normalize_city("Portland, OR") == "Portland"

    def test_strips_two_letter_suffix_no_comma(self):
        assert normalize_city("Toronto ON") == "Toronto"

    def test_strips_country_after_comma(self):
        assert normalize_city("London, UK") == "London"
        assert normalize_city("Paris, France") == "Paris"

    def test_title_cases_result(self):
        assert normalize_city("san francisco, CA") == "San Francisco"
        assert normalize_city("TORONTO, ON") == "Toronto"

    def test_plain_city_unchanged(self):
        assert normalize_city("Calgary") == "Calgary"

    def test_mixed_case_city(self):
        assert normalize_city("vANcOUVER") == "Vancouver"

    def test_extra_whitespace_plus_suffix(self):
        assert normalize_city("  Edmonton ,  AB  ") == "Edmonton"

    def test_two_word_city_with_suffix(self):
        assert normalize_city("Fort McMurray, AB") == "Fort Mcmurray"

    def test_empty_string_returns_empty(self):
        assert normalize_city("") == ""


# ── normalize_industry ────────────────────────────────────────────────────────

class TestNormalizeIndustry:
    def test_exact_canonical_mixed_case(self):
        assert normalize_industry("Construction") == "Construction"
        assert normalize_industry("RETAIL") == "Retail"
        assert normalize_industry("technology") == "Technology"
        assert normalize_industry("Healthcare") == "Healthcare"
        assert normalize_industry("Manufacturing") == "Manufacturing"
        assert normalize_industry("Real Estate") == "Real Estate"
        assert normalize_industry("Professional Services") == "Professional Services"

    def test_tech_alias(self):
        assert normalize_industry("tech") == "Technology"

    def test_software_alias(self):
        assert normalize_industry("software") == "Technology"

    def test_it_alias(self):
        assert normalize_industry("IT") == "Technology"

    def test_information_technology_alias(self):
        assert normalize_industry("Information Technology") == "Technology"

    def test_health_care_two_words(self):
        assert normalize_industry("health care") == "Healthcare"

    def test_health_alias(self):
        assert normalize_industry("health") == "Healthcare"

    def test_medical_alias(self):
        assert normalize_industry("medical") == "Healthcare"

    def test_mfg_alias(self):
        assert normalize_industry("mfg") == "Manufacturing"

    def test_realestate_no_space(self):
        assert normalize_industry("realestate") == "Real Estate"

    def test_property_alias(self):
        assert normalize_industry("property") == "Real Estate"

    def test_consulting_alias(self):
        assert normalize_industry("consulting") == "Professional Services"

    def test_prof_services_alias(self):
        assert normalize_industry("prof services") == "Professional Services"

    def test_strips_and_collapses_whitespace(self):
        assert normalize_industry("  retail  ") == "Retail"
        assert normalize_industry("  real   estate  ") == "Real Estate"

    def test_unknown_returns_none(self):
        assert normalize_industry("Fintech") is None
        assert normalize_industry("Unknown Industry") is None
        assert normalize_industry("") is None
        assert normalize_industry("   ") is None


# ── SUPPORTED_INDUSTRIES ──────────────────────────────────────────────────────

def test_supported_industries_is_non_empty_tuple():
    assert isinstance(SUPPORTED_INDUSTRIES, tuple)
    assert len(SUPPORTED_INDUSTRIES) >= 7


def test_all_supported_industries_normalize_to_themselves():
    """Every canonical name round-trips through normalize_industry."""
    for name in SUPPORTED_INDUSTRIES:
        assert normalize_industry(name) == name, f"{name!r} did not round-trip"


# ── get_template case-insensitive lookup ──────────────────────────────────────

class TestGetTemplate:
    def test_lowercase_input(self):
        assert get_template("construction").industry_name == "Construction"

    def test_alias_input(self):
        assert get_template("tech").industry_name == "Technology"

    def test_mixed_case(self):
        assert get_template("RETAIL").industry_name == "Retail"

    def test_real_estate_lowercase(self):
        assert get_template("real estate").industry_name == "Real Estate"

    def test_unknown_falls_back_to_construction(self):
        assert get_template("XYZ Unknown").industry_name == "Construction"


# ── CLI: invalid industry validation ─────────────────────────────────────────

def test_cli_run_invalid_industry_exits_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """cmd_run returns 1 and prints a helpful error when industry is unrecognised."""
    from marketscout.cli import cmd_run

    exit_code = cmd_run(
        city="Vancouver", industry="Fintech", out_dir=tmp_path / "out",
        jobs_limit=5, headlines_limit=5, jobs_provider="rss",
        allow_provider_fallback=False, write_leads=False, refresh=False, deterministic=False,
    )
    assert exit_code == 1
    stderr = capsys.readouterr().err
    assert "unrecognised industry" in stderr.lower() or "Fintech" in stderr
    assert any(ind in stderr for ind in SUPPORTED_INDUSTRIES)


def test_cli_run_normalizes_city_and_industry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """cmd_run normalizes 'Vancouver, BC' → 'Vancouver' and 'construction' → 'Construction'."""
    _RSS = """<?xml version="1.0"?><rss><channel>
  <item><title>Test</title><link>https://a.com</link></item>
  <item><title>Test B</title><link>https://b.com</link></item>
</channel></rss>"""

    class _FakeResp:
        text = _RSS
        def raise_for_status(self): pass

    monkeypatch.setattr(_ms_headlines.requests, "get", lambda *a, **k: _FakeResp())
    monkeypatch.setattr(_ms_rss.requests, "get", lambda *a, **k: _FakeResp())

    from marketscout.cli import cmd_run

    out_dir = tmp_path / "out"
    exit_code = cmd_run(
        city="Vancouver, BC", industry="construction", out_dir=out_dir,
        jobs_limit=5, headlines_limit=5, jobs_provider="rss",
        allow_provider_fallback=False, write_leads=False, refresh=False, deterministic=False,
    )
    assert exit_code == 0
    strategy = json.loads((out_dir / "strategy.json").read_text())
    assert strategy["city"] == "Vancouver"
    assert strategy["industry"] == "Construction"
