"""Jobs providers: pluggable backends (Adzuna, RSS)."""

from marketscout.scout.providers.adzuna import AdzunaProvider
from marketscout.scout.providers.base import JobsProvider
from marketscout.scout.providers.rss import RssJobsProvider

__all__ = ["JobsProvider", "AdzunaProvider", "RssJobsProvider"]
