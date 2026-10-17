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
    "get_available_scrapers",
]


def get_available_scrapers():
    scrapers = []
    try:
        scrapers.append(DevpostScraper())
    except Exception:
        pass
    try:
        scrapers.append(EventbriteScraper())
    except Exception:
        pass
    try:
        scrapers.append(GDGScraper())
    except Exception:
        pass
    try:
        scrapers.append(JOSAScraper())
    except Exception:
        pass
    try:
        scrapers.append(ManualScraper())
    except Exception:
        pass
    return scrapers

