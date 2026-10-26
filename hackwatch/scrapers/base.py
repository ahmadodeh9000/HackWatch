import abc
import time
from typing import List, Optional
import requests
from hackwatch import __version__
from hackwatch.models import Event

# Say honestly who we are and where to find us, so site owners can get in touch.
DEFAULT_USER_AGENT = f"HackWatch/{__version__} (+https://github.com/ahmadodeh9000/HackWatch)"


class BaseScraper(abc.ABC):
    name: str = "base"
    # The defaults below are set per source from sources.yaml (see hackwatch/sources.py).
    # Applied by cli.run_fetch to events that don't set their own type.
    default_type: Optional[str] = None
    # Added by cli.run_fetch to every event from this scraper.
    default_tags: List[str] = []
    # jordan | worldwide; applied to events that don't set their own scope.
    default_scope: Optional[str] = None
    # If set, type inference may only pick from these (e.g. Devpost: hackathon, competition).
    allowed_types: Optional[List[str]] = None

    def __init__(self, delay_seconds: float = 2.0):
        self.delay_seconds = delay_seconds
        self.last_request_time: float = 0.0
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": DEFAULT_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        })

    def request(self, method: str, url: str, **kwargs) -> requests.Response:
        """Execute HTTP request enforcing the delay between consecutive calls."""
        elapsed = time.time() - self.last_request_time
        if self.last_request_time > 0 and elapsed < self.delay_seconds:
            time.sleep(self.delay_seconds - elapsed)
        resp = self.session.request(method, url, **kwargs)
        self.last_request_time = time.time()
        resp.raise_for_status()
        return resp

    def get(self, url: str, **kwargs) -> requests.Response:
        return self.request("GET", url, **kwargs)

    @abc.abstractmethod
    def fetch(self) -> List[Event]:
        """Fetch and return a list of Event objects from this source."""
        pass
