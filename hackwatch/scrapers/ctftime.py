import re
from datetime import datetime, timedelta, timezone
from typing import List

from hackwatch.models import Event
from hackwatch.scrapers.base import BaseScraper
from hackwatch.scrapers.registry import register
from hackwatch.timeutil import local_date


# A money amount with its currency before ("$900", "USD 2,500") or after ("1 500 €", "1100$").
_CURRENCY = r"(?P<cur>US\$|\$|€|£|USD|EUR|GBP|JOD|SAR|AED|INR)"
_NUMBER = r"(?P<num>\d{1,3}(?:[,.\u00a0\u202f ]\d{3})+|\d+)(?:\s?(?P<k>[kK])(?![a-zA-Z]))?"
_AMOUNT_BEFORE = re.compile(_CURRENCY + r"\s?" + _NUMBER)
_AMOUNT_AFTER = re.compile(_NUMBER + r"\s?" + _CURRENCY.replace("?P<cur>", "?P<cur2>"))
_SYMBOLS = {"$": "$", "US$": "$", "€": "€", "£": "£"}
# Words before an amount that mean "at least this much".
_MORE_THAN = re.compile(r"(more than|over|at least|plus de|\+)\s*$", re.I)


def extract_prize(text: str) -> str:
    """A short prize amount from CTFtime's free-text 'prizes' field, or "" if none.

    "This year's prize pool stands at $900 USD..." -> "$900";
    "Plus de 1 500 € de lots..." -> "€1,500+"; "See https://..." -> "".
    The first amount is used: organisers usually lead with the total pool.
    """
    text = text or ""
    matches = [m for m in (_AMOUNT_BEFORE.search(text), _AMOUNT_AFTER.search(text)) if m]
    if not matches:
        return ""
    m = min(matches, key=lambda m: m.start())
    currency = m.group("cur") if "cur" in m.groupdict() else m.group("cur2")
    value = int(re.sub(r"\D", "", m.group("num"))) * (1000 if m.group("k") else 1)
    if value == 0:
        return ""
    amount = f"{_SYMBOLS[currency]}{value:,}" if currency in _SYMBOLS else f"{currency} {value:,}"
    more = text[m.end():m.end() + 1] == "+" or _MORE_THAN.search(text[max(0, m.start() - 15):m.start()])
    return amount + ("+" if more else "")


@register("ctftime")
class CTFtimeScraper(BaseScraper):
    """Upcoming CTFs from the public CTFtime API (https://ctftime.org/api/)."""

    api_url = "https://ctftime.org/api/v1/events/"

    def __init__(self, days_ahead: int = 60, limit: int = 100, delay_seconds: float = 2.0):
        super().__init__(delay_seconds=delay_seconds)
        self.days_ahead = days_ahead
        self.limit = limit

    def fetch(self) -> List[Event]:
        # Window starts at today's midnight UTC so the request URL is the same all day.
        now = datetime.now(timezone.utc)
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        finish = start + timedelta(days=self.days_ahead)
        resp = self.get(self.api_url, params={
            "limit": self.limit, "start": int(start.timestamp()), "finish": int(finish.timestamp()),
        })
        events = []
        for item in resp.json():
            title, url = item.get("title"), item.get("ctftime_url") or item.get("url")
            if not title or not url:
                continue
            onsite = bool(item.get("onsite"))
            details = [item.get("format"), item.get("restrictions")]
            summary = " · ".join(d for d in details if d)
            text = " ".join((item.get("description") or "").split())
            description = f"{summary} CTF. {text}"[:600] if summary else text[:600]
            # The prizes field is free text (paragraphs, links, other languages): keep a short
            # amount for the prize badge and put the full text at the end of the description.
            prize_text = " ".join((item.get("prizes") or "").split())
            if prize_text:
                description = f"{description} Prizes: {prize_text[:400]}".strip()
            events.append(Event(
                title=title,
                url=url,
                source=self.name,
                organizer=", ".join(o["name"] for o in item.get("organizers") or [] if o.get("name")) or None,
                prize=extract_prize(prize_text) or None,
                start_date=local_date(item.get("start")),
                end_date=local_date(item.get("finish")),
                mode="in-person" if onsite else "online",
                location=(item.get("location") or None) if onsite else "Online",
                description=description,
            ))
        return events
