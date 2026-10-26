import abc
import time
from typing import List, Optional
import requests
from hackwatch import __version__
from hackwatch.models import Event

# Say honestly who we are and where to find us, so site owners can get in touch.
DEFAULT_USER_AGENT = f"HackWatch/{__version__} (+https://github.com/ahmadodeh9000/HackWatch)"


# Text that anti-bot pages show instead of the real content (often with a 200 status).
BLOCK_MARKERS = ("captcha", "challenge-platform", "attention required", "access denied",
                 "request rejected", "are you a robot", "unusual traffic", "datadome",
                 "px-captcha", "verify you are human")


def block_hint(resp) -> Optional[str]:
    """A short reason if the response looks like a block/rate-limit page, else None."""
    headers = {k.lower(): v for k, v in (resp.headers or {}).items()}
    reasons = []
    if resp.status_code in (403, 429, 503):
        reasons.append(f"HTTP {resp.status_code}")
    if headers.get("retry-after"):
        reasons.append(f"Retry-After: {headers['retry-after']}")
    if headers.get("cf-mitigated"):
        reasons.append(f"cf-mitigated: {headers['cf-mitigated']}")
    if "json" not in headers.get("content-type", ""):
        head = (resp.content or b"")[:30000].decode("utf-8", "ignore").lower()
        found = [m for m in BLOCK_MARKERS if m in head]
        if found:
            reasons.append("page mentions " + ", ".join(repr(m) for m in found[:3]))
    return "; ".join(reasons) or None


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
    # Keep only events with a tech keyword (for general listings like Eventbrite).
    require_tech_keywords: bool = False
    # Guess tags from title/description. Off for sources whose text lists unrelated
    # topics (CTF descriptions list challenge categories like web/crypto/hardware).
    infer_tags: bool = True

    timeout_seconds: float = 60.0

    def __init__(self, delay_seconds: float = 2.0):
        self.request_log: List[dict] = []
        self.delay_seconds = delay_seconds
        self.last_request_time: float = 0.0
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": DEFAULT_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        })

    def request(self, method: str, url: str, **kwargs) -> requests.Response:
        """Execute HTTP request enforcing the delay between consecutive calls.

        Every request is recorded in self.request_log (status, time, size, error)
        so a fetch can report why a source came back empty.
        """
        elapsed = time.time() - self.last_request_time
        if self.last_request_time > 0 and elapsed < self.delay_seconds:
            time.sleep(self.delay_seconds - elapsed)
        # Never wait forever on a stuck site: the daily CI job would hang.
        kwargs.setdefault("timeout", self.timeout_seconds)
        entry = {"url": requests.Request(method, url, params=kwargs.get("params")).prepare().url}
        started = time.monotonic()
        try:
            resp = self.session.request(method, url, **kwargs)
        except requests.RequestException as exc:
            entry.update(status=None, seconds=round(time.monotonic() - started, 2),
                         error=f"{type(exc).__name__}: {str(exc)[:200]}")
            self.request_log.append(entry)
            raise
        finally:
            self.last_request_time = time.time()
        entry.update(status=resp.status_code, seconds=round(time.monotonic() - started, 2),
                     bytes=len(resp.content or b""), hint=block_hint(resp))
        self.request_log.append(entry)
        resp.raise_for_status()
        return resp

    def get(self, url: str, **kwargs) -> requests.Response:
        return self.request("GET", url, **kwargs)

    @abc.abstractmethod
    def fetch(self) -> List[Event]:
        """Fetch and return a list of Event objects from this source."""
        pass
