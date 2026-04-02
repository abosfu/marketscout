"""Scout: fetch headlines and job signals."""

from marketscout.scout.errors import ScoutError
from marketscout.scout.headlines import fetch_headlines
from marketscout.scout.jobs import fetch_jobs

__all__ = ["ScoutError", "fetch_headlines", "fetch_jobs"]
