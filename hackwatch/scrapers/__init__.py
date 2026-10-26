"""Scrapers register themselves by name (see registry.py); sources.yaml says which run."""
from hackwatch.scrapers.base import BaseScraper
from hackwatch.scrapers.registry import SCRAPERS, register

# Importing the modules registers their scraper classes.
from hackwatch.scrapers import devpost, eventbrite, gdg, josa, manual  # noqa: F401,E402

__all__ = ["BaseScraper", "SCRAPERS", "register", "get_available_scrapers"]


def get_available_scrapers(include_disabled: bool = False):
    """Scrapers for the sources in sources.yaml (enabled ones only, by default)."""
    from hackwatch.sources import build_scrapers  # late import: sources imports this package
    return build_scrapers(include_disabled=include_disabled)
