"""Leads builder: aggregate jobs into company-level leads for export."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Iterable, List

from marketscout.scout.providers.base import JobItem


READINESS_KEYWORDS = (
    "coordinator",
    "dispatcher",
    "scheduler",
    "data entry",
    "administrator",
    "assistant",
    "bookkeeper",
)


@dataclass
class LeadRow:
    """Single lead row for CSV export."""

    company: str
    job_count: int
    top_keywords: str
    readiness_score: int  # 0–100
    example_links: str


def _extract_keywords(text: str) -> Iterable[str]:
    """Yield readiness keywords present in the given text (case-insensitive)."""
    lower = text.lower()
    for kw in READINESS_KEYWORDS:
        if kw in lower:
            yield kw


def _score_lead(job_count: int, keyword_hits: int) -> int:
    """
    Compute readiness_score (0–100) from job count and keyword hits.

    Heuristic:
    - Base 20 points if there is at least one job.
    - +10 per keyword hit (up to 5 keywords => +50).
    - +10 per job beyond the first (up to +30).
    - Cap at 100.
    """
    if job_count <= 0:
        return 0
    score = 20
    score += min(50, keyword_hits * 10)
    score += min(30, max(0, job_count - 1) * 10)
    return max(0, min(100, score))


def build_leads(jobs: List[JobItem]) -> List[LeadRow]:
    """
    Build LeadRow list from normalized JobItem dicts.

    Aggregates by company name, computes job_count, top_keywords, readiness_score,
    and example_links (comma-separated URLs).
    """
    # Group jobs by company (fallback to "Unknown" if missing)
    grouped: dict[str, list[JobItem]] = defaultdict(list)
    display_names: dict[str, str] = {}
    for job in jobs:
        raw_name = (job.get("company") or "").strip()
        if not raw_name:
            raw_name = "Unknown"
        key = raw_name.lower()
        grouped[key].append(job)
        # Preserve the first-seen casing
        display_names.setdefault(key, raw_name)

    leads: list[LeadRow] = []
    for key, company_jobs in grouped.items():
        company_name = display_names.get(key, key)
        job_count = len(company_jobs)

        # Aggregate keywords from job titles
        kw_counter: Counter[str] = Counter()
        for job in company_jobs:
            title = (job.get("title") or "").strip()
            for kw in _extract_keywords(title):
                kw_counter[kw] += 1
        keyword_hits = sum(kw_counter.values())
        # Build top_keywords comma string, most frequent first
        top_keywords_list = [kw for kw, _ in kw_counter.most_common(3)]
        top_keywords = ", ".join(top_keywords_list)

        # Example links: up to 3 distinct URLs
        links_seen: list[str] = []
        for job in company_jobs:
            link = (job.get("link") or "").strip()
            if link and link not in links_seen:
                links_seen.append(link)
            if len(links_seen) >= 3:
                break
        example_links = ", ".join(links_seen)

        readiness_score = _score_lead(job_count=job_count, keyword_hits=keyword_hits)
        leads.append(
            LeadRow(
                company=company_name,
                job_count=job_count,
                top_keywords=top_keywords,
                readiness_score=readiness_score,
                example_links=example_links,
            )
        )

    # Sort by readiness_score desc, then job_count desc, then company name
    leads.sort(key=lambda r: (-r.readiness_score, -r.job_count, r.company.lower()))
    return leads

