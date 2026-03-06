"""Jobs provider interface: pluggable backends for job listings."""

from __future__ import annotations

from typing import Protocol

# Job item: dict with title, company, location, link, published, source (normalized shape)
JobItem = dict[str, str]


class JobsProvider(Protocol):
    """Protocol for job listing providers. Implementations return normalized JobItem dicts."""

    def fetch_jobs(self, city: str, industry: str, limit: int) -> list[JobItem]:
        """Fetch job listings for the given city and industry. Returns list of normalized job dicts."""
        ...
