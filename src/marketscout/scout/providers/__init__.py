"""Jobs providers: pluggable backends (SerpAPI, Adzuna, RSS)."""

from marketscout.scout.providers.adzuna import AdzunaProvider
from marketscout.scout.providers.base import JobsProvider
from marketscout.scout.providers.rss import RssJobsProvider
from marketscout.scout.providers.serpapi import SerpApiJobsProvider

__all__ = ["JobsProvider", "AdzunaProvider", "RssJobsProvider", "SerpApiJobsProvider"]
