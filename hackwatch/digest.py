"""'This week in Jordan tech': the next 7 days of Jordan events plus deadlines closing soon.

Two formats: plain text for WhatsApp/Telegram (short lines, few emojis, one link per
event) and Markdown. Links go to each event's page on the site (docs/e/<id>.html),
which previews nicely when shared and links on to the organiser's page.
"""
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Iterable, List, Optional

from hackwatch.models import Event
from hackwatch.tidy import shown_title

SITE_URL = "https://ahmadodeh9000.github.io/HackWatch/"
SUBMIT_URL = "https://github.com/ahmadodeh9000/HackWatch/issues/new?template=event.yml"
DAYS = 7


def event_page_url(event: Event, site: str = SITE_URL) -> str:
    return f"{site.rstrip('/')}/e/{event.id}.html"


@dataclass
class Digest:
    start: date
    end: date
    this_week: List[Event]
    closing: List[Event]   # registration closes within the window (events may start later)


def _day(d: Optional[str]) -> Optional[date]:
    try:
        return date.fromisoformat(d[:10]) if d else None
    except ValueError:
        return None


def build_digest(events: Iterable[Event], today: Optional[date] = None, days: int = DAYS) -> Digest:
    """Jordan events, without club-life ones, starting in [today, today + days)."""
    today = today or date.today()
    end = today + timedelta(days=days - 1)
    chosen = [e for e in events if e.scope == "jordan" and not e.low_signal]
    this_week = sorted((e for e in chosen if (d := _day(e.start_date)) and today <= d <= end),
                       key=lambda e: (e.start_date, e.start_time or "", e.title))
    listed = {e.id for e in this_week}
    closing = sorted((e for e in chosen if (d := _day(e.registration_deadline)) and today <= d <= end
                      and e.id not in listed),
                     key=lambda e: (e.registration_deadline, e.title))
    return Digest(today, end, this_week, closing)


def _when(e: Event) -> str:
    d = _day(e.start_date)
    text = d.strftime("%a %-d %b") if d else "TBA"
    return f"{text}, {e.start_time}" if e.start_time else text


def _where(e: Event) -> str:
    if e.mode == "online":
        return "Online"
    place = (e.location or "").replace(", Jordan", "").strip(", ")
    return place + (" + online" if e.mode == "hybrid" else "")


def _short(text: str, limit: int = 60) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def to_text(digest: Digest, site: str = SITE_URL) -> str:
    """Plain text for WhatsApp/Telegram: one block per event, one link each."""
    span = f"{digest.start.strftime('%-d %b')} – {digest.end.strftime('%-d %b')}"
    lines = ["📅 This week in Jordan tech", "هذا الأسبوع في فعاليات التقنية بالأردن", span, ""]
    if not digest.this_week:
        lines += ["No events listed for this week yet.", "لا توجد فعاليات مدرجة لهذا الأسبوع بعد.", ""]
    for e in digest.this_week:
        lines += [f"• {_short(shown_title(e))}", f"  {_when(e)} · {_where(e)} · {e.type or 'other'}", f"  {event_page_url(e, site)}", ""]
    if digest.closing:
        lines += ["⏳ Registration closing soon | التسجيل يُغلق قريباً"]
        for e in digest.closing:
            closes = _day(e.registration_deadline).strftime("%a %-d %b")
            lines += [f"• {_short(shown_title(e))} (closes {closes})", f"  {event_page_url(e, site)}"]
        lines.append("")
    lines += [f"All events | كل الفعاليات: {site}", f"Add yours | أضف فعاليتك: {SUBMIT_URL}"]
    return "\n".join(lines) + "\n"


def to_markdown(digest: Digest, site: str = SITE_URL) -> str:
    span = f"{digest.start.strftime('%-d %b')} – {digest.end.strftime('%-d %b %Y')}"
    lines = ["# This week in Jordan tech · هذا الأسبوع في التقنية بالأردن", "", f"_{span}_", ""]
    if not digest.this_week:
        lines += ["No events listed for this week yet.", ""]
    for e in digest.this_week:
        lines.append(f"- **[{shown_title(e)}]({event_page_url(e, site)})**: {_when(e)} · {_where(e)} · {e.type or 'other'}")
    if digest.closing:
        lines += ["", "## Registration closing soon · التسجيل يُغلق قريباً", ""]
        for e in digest.closing:
            closes = _day(e.registration_deadline).strftime("%a %-d %b")
            lines.append(f"- [{shown_title(e)}]({event_page_url(e, site)}): closes {closes}")
    lines += ["", f"[All events]({site}) · [Add your event]({SUBMIT_URL})"]
    return "\n".join(lines) + "\n"
