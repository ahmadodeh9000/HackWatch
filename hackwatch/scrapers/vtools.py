import re
from typing import List

import requests
from bs4 import BeautifulSoup

from hackwatch.models import Event
from hackwatch.scrapers.base import BaseScraper
from hackwatch.scrapers.registry import register
from hackwatch.timeutil import deadline_date, local_date, local_time

LOCATION_MODES = {"physical": "in-person", "virtual": "online", "hybrid": "hybrid"}
# Posts that report on a past activity rather than announce one. vTools has no field for
# this (enhanced-report is empty on them), so the title is the only signal.
REPORT_RE = re.compile(r"\breports?\b|تقرير", re.I)
# Reports also come dated in the future and titled like events ("Booth Participation at IEEE
# Day - AAU", 27 Nov: "The Student Branch hosted an exhibition booth..."), so the description
# counts too: past-tense wording, unless it also invites people to come.
PAST_TENSE_RE = re.compile(
    r"\b(?:hosted(?! by)|organi[sz]ed(?! by)|(?:was|were) (?:held|conducted|organi[sz]ed|hosted)|took place|"
    r"participated in|concluded|attended by)\b|أقيمت|أقيم|عُقدت|عقدت|تم عقد|تم تنظيم", re.I)
INVITATION_RE = re.compile(
    r"\b(?:join|register|registration|will|invited?|don'?t miss|come|upcoming event|aims? to)\b|انضم|سجل|سجّل|ندعو|سيتم|ستقام", re.I)
# Student branch (STB), its chapters (SBC... + letter) and affinity groups (SBA) share the
# branch number: STB25091, SBC25091A and SBA25091 are all Yarmouk University.
BRANCH_SPOID_RE = re.compile(r"^(?:STB|SBC|SBA)(\d+)")


def branch_key(spoid: str) -> str:
    m = BRANCH_SPOID_RE.match(spoid or "")
    return f"branch-{m.group(1)}" if m else (spoid or "")


def reads_like_report(description: str) -> bool:
    return bool(PAST_TENSE_RE.search(description or "")) and not INVITATION_RE.search(description or "")


def html_to_text(html: str, limit: int = 600) -> str:
    return " ".join(BeautifulSoup(html or "", "html.parser").get_text(" ").split())[:limit]


@register("vtools")
class VToolsScraper(BaseScraper):
    """IEEE events from the public vTools Events API, kept only for the given sections.

    The public API can't filter by section (per-section feeds need a request to
    IEEE staff), so this pages through all upcoming events worldwide and keeps
    those hosted or co-hosted by `section_spoids` (Jordan Section = R80079).
    """

    api_url = "https://events.vtools.ieee.org/RST/events/api/public/v8/events/list"

    def __init__(self, section_spoids: List[str], days_ahead: int = 60, page_size: int = 100,
                 max_pages: int = 20, delay_seconds: float = 2.0):
        super().__init__(delay_seconds=delay_seconds)
        if not section_spoids:
            raise ValueError("vtools needs section_spoids (e.g. [R80079] for the Jordan Section)")
        self.section_spoids = set(section_spoids)
        self.days_ahead = days_ahead
        self.page_size = page_size
        self.max_pages = max_pages

    def _page(self, page: int) -> dict:
        params = {"span": f"now~now+{self.days_ahead}", "limit": self.page_size, "page": page}
        try:
            return self.get(self.api_url, params=params).json()
        except requests.Timeout:
            return self.get(self.api_url, params=params).json()  # the API is slow at times; retry once

    def _in_sections(self, attrs: dict) -> bool:
        hosts = [attrs.get("primary-host") or {}] + list(attrs.get("cohosts") or [])
        for host in hosts:
            spoids = str(host.get("section_spoids") or "").replace(";", ",").split(",")
            if self.section_spoids & {s.strip() for s in spoids}:
                return True
        return False

    def fetch(self) -> List[Event]:
        events = []
        page, total_pages = 1, 1
        while page <= min(total_pages, self.max_pages):
            data = self._page(page)
            total_pages = int(((data.get("meta") or {}).get("paging") or {}).get("total_pages") or 1)
            for item in data.get("data") or []:
                attrs = item.get("attributes") or {}
                if not attrs.get("title") or not self._in_sections(attrs):
                    continue
                if attrs.get("cancelled") or REPORT_RE.search(attrs["title"]):
                    continue
                if reads_like_report(html_to_text(attrs.get("description"))):
                    continue
                mode = LOCATION_MODES.get(str(attrs.get("location-type") or "").lower(), "in-person")
                # City names are typed freely ("amman", "Az Zarqa"); capitalise all-lowercase ones.
                place = [p.strip() for p in (attrs.get("building"), attrs.get("city")) if p and p.strip()]
                place = [p.title() if p.islower() else p for p in place]
                location = "Online" if mode == "online" else ", ".join(place + ["Jordan"])
                host = attrs.get("primary-host") or {}
                events.append(Event(
                    title=" ".join(attrs["title"].split()),
                    url=f"https://events.vtools.ieee.org/m/{attrs.get('id') or item.get('id')}",
                    source=self.name,
                    organizer=host.get("name"),
                    prize="N/A",
                    # Dates and clock times in Amman: the event's own time zone is often
                    # wrong (Jordan events set to Europe/Istanbul or Africa/Cairo).
                    registration_deadline=deadline_date(attrs.get("registration-end-time")),
                    start_date=local_date(attrs.get("start-time")),
                    end_date=local_date(attrs.get("end-time")),
                    start_time=local_time(attrs.get("start-time")),
                    end_time=local_time(attrs.get("end-time")),
                    mode=mode,
                    location=location,
                    country="JO",
                    description=html_to_text(attrs.get("description")),
                    source_labels=[str(t).lstrip("#") for t in attrs.get("tags") or []],
                    host_key=branch_key(host.get("spoid")) or None,
                ))
            page += 1
        return events
