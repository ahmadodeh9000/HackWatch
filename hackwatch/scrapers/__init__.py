from hackwatch.scrapers.base import BaseScraper
from hackwatch.scrapers.devpost import DevpostScraper
from hackwatch.scrapers.manual import ManualScraper
from hackwatch.scrapers.eventbrite import EventbriteScraper
from hackwatch.scrapers.gdg import GDGScraper
from hackwatch.scrapers.josa import JOSAScraper

__all__ = [
    "BaseScraper",
    "DevpostScraper",
    "ManualScraper",
    "EventbriteScraper",
    "GDGScraper",
    "JOSAScraper",
]
