"""What search engines and feed readers read: Event JSON-LD, sitemap.xml and feed.xml (Atom)."""
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional
from xml.sax.saxutils import escape

from hackwatch.digest import SITE_URL, event_page_url
from hackwatch.models import Event
from hackwatch.tidy import shown_title

ATTENDANCE = {"online": "OnlineEventAttendanceMode", "in-person": "OfflineEventAttendanceMode",
              "hybrid": "MixedEventAttendanceMode"}
AMMAN_OFFSET = "+03:00"   # Jordan has stayed on UTC+3 all year since 2022
MAX_FEED_ENTRIES = 50


def _stamp(day: Optional[str], clock: Optional[str]) -> Optional[str]:
    if not day:
        return None
    return f"{day[:10]}T{clock}:00{AMMAN_OFFSET}" if clock else day[:10]


def event_jsonld(e: Event, site: str = SITE_URL) -> dict:
    """schema.org Event for one share page; only what we actually know."""
    online = {"@type": "VirtualLocation", "url": e.url}
    place = {"@type": "Place", "name": (e.location or "Jordan").split(",")[0].strip(),
             "address": {"@type": "PostalAddress", "streetAddress": e.location or "", "addressCountry": e.country or "JO"}}
    data = {
        "@context": "https://schema.org",
        "@type": "Event",
        "name": shown_title(e),
        "url": e.url,
        "startDate": _stamp(e.start_date, e.start_time),
        "endDate": _stamp(e.end_date or e.start_date, e.end_time if e.start_time else None),
        "eventStatus": "https://schema.org/EventScheduled",
        "eventAttendanceMode": "https://schema.org/" + ATTENDANCE.get(e.mode, ATTENDANCE["in-person"]),
        "location": online if e.mode == "online" else [place, online] if e.mode == "hybrid" else place,
        "image": [f"{site.rstrip('/')}/og.png"],
    }
    if e.description:
        data["description"] = " ".join(e.description.split())[:500]
    if e.organizer:
        data["organizer"] = {"@type": "Organization", "name": e.organizer}
    if e.cost == "free":
        data["isAccessibleForFree"] = True
    return {k: v for k, v in data.items() if v is not None}


def jsonld_script(e: Event, site: str = SITE_URL) -> str:
    # "<" escaped so an event's text can't close the script tag.
    body = json.dumps(event_jsonld(e, site), ensure_ascii=False).replace("<", "\\u003c")
    return f'<script type="application/ld+json">{body}</script>'


def build_sitemap(events: Iterable[Event], site: str = SITE_URL) -> str:
    urls = [site] + [event_page_url(e, site) for e in events if e.id]
    rows = "".join(f"  <url><loc>{escape(u)}</loc></url>\n" for u in urls)
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n{rows}</urlset>\n')


def first_seen_dates(previous: Optional[List[dict]]) -> Dict[str, str]:
    """{event id: date first listed} from the last deployed events.json (series: every session)."""
    seen: Dict[str, str] = {}
    for record in previous or []:
        when = record.get("first_seen")
        if not when:
            continue
        for key in [record.get("id")] + [s.get("id") for s in record.get("sessions") or []]:
            if key:
                seen[key] = when
    return seen


def build_feed(events: Iterable[Event], first_seen: Dict[str, str], site: str = SITE_URL,
               today: Optional[date] = None) -> str:
    """Atom feed of Jordan events, newest listed first (club life left out, as in the digest)."""
    today = (today or datetime.now(timezone.utc).date()).isoformat()
    chosen = [e for e in events if e.scope == "jordan" and not e.low_signal and e.id]
    chosen.sort(key=lambda e: (first_seen.get(e.id, today), e.start_date or ""), reverse=True)
    chosen = chosen[:MAX_FEED_ENTRIES]
    root = site.rstrip("/")
    entries = []
    for e in chosen:
        when = first_seen.get(e.id, today) + "T00:00:00Z"
        place = "Online" if e.mode == "online" else (e.location or "")
        start = " ".join(filter(None, [e.start_date, e.start_time]))
        summary = " · ".join(filter(None, [start, place, e.organizer]))
        if e.description:
            summary += "\n\n" + " ".join(e.description.split())[:400]
        entries.append(
            "  <entry>\n"
            f"    <title>{escape(shown_title(e))}</title>\n"
            f'    <link href="{escape(event_page_url(e, site), {chr(34): "&quot;"})}"/>\n'
            f"    <id>{escape(event_page_url(e, site))}</id>\n"
            f"    <published>{when}</published>\n"
            f"    <updated>{when}</updated>\n"
            f"    <summary>{escape(summary)}</summary>\n"
            "  </entry>\n")
    updated = (max((first_seen.get(e.id, today) for e in chosen), default=today)) + "T00:00:00Z"
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<feed xmlns="http://www.w3.org/2005/Atom">\n'
            "  <title>HackWatch: new tech events in Jordan</title>\n"
            f'  <link href="{root}/feed.xml" rel="self"/>\n'
            f'  <link href="{root}/"/>\n'
            f"  <id>{root}/feed.xml</id>\n"
            f"  <updated>{updated}</updated>\n"
            "  <author><name>HackWatch</name></author>\n"
            + "".join(entries) + "</feed>\n")
