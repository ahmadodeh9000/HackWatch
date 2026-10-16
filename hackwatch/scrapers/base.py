import abc
import time
from typing import List, Optional
import requests
from hackwatch.models import Event

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


class BaseScraper(abc.ABC):
    name: str = "base"

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
