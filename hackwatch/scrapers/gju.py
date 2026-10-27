"""German Jordanian University events calendar (Drupal month view, server-rendered).

https://www.gju.edu.jo/gju-event/month/YYYY-MM lists each event as a box with a
title and dates in machine-readable attributes, and links it to its /content/ page.
GJU's robots.txt asks for 10 seconds between requests.
"""
import re
from datetime import date
from typing import List, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from hackwatch.models import Event
from hackwatch.scrapers.base import BaseScraper
from hackwatch.scrapers.registry import register
from hackwatch.timeutil import local_date


def month_keys(today: date, months_ahead: int) -> List[str]:
    keys = []
    year, month = today.year, today.month
    for _ in range(months_ahead + 1):
        keys.append(f"{year:04d}-{month:02d}")
        month += 1
        if month == 13:
            year, month = year + 1, 1
    return keys


def parse_month(html: str, base_url: str) -> List[dict]:
    soup = BeautifulSoup(html, "html.parser")
    items = []
    for box in soup.select("div[id^=colorbox-inline-]"):
        title = box.select_one(".event-title")
        dates = [el["content"] for el in box.select(".event-body [content]") if el.get("content")]
        if not title or not dates:
            continue
        link = soup.find("a", href=re.compile(re.escape(box["id"]) + "$"))
        href = link["href"].split("?")[0].split("#")[0] if link else None
        body = box.select_one(".event-body")
        text = " ".join(p.get_text(" ", strip=True) for p in body.find_all("p")) if body else ""
        items.append({
            "title": " ".join(title.get_text(" ").split()),
            "start": dates[0],
            "end": dates[-1],
            "url": urljoin(base_url, href) if href else f"{base_url.rstrip('/')}/gju-event#{box['id']}",
            "description": text,
        })
    return items


@register("gju")
class GJUScraper(BaseScraper):
    def __init__(self, base_url: str = "https://www.gju.edu.jo", months_ahead: int = 2,
                 delay_seconds: float = 10.0):
        super().__init__(delay_seconds=delay_seconds)
        self.base_url = base_url
        self.months_ahead = months_ahead

    def fetch(self, today: Optional[date] = None) -> List[Event]:
        today = today or date.today()
        events, seen = [], set()
        for key in month_keys(today, self.months_ahead):
            html = self.get(f"{self.base_url.rstrip('/')}/gju-event/month/{key}").text
            for item in parse_month(html, self.base_url):
                if item["url"] in seen:
                    continue  # multi-day events show up in every month they span
                seen.add(item["url"])
                description = item["description"] if item["description"] != item["title"] else None
                events.append(Event(
                    title=item["title"],
                    url=item["url"],
                    source=self.name,
                    organizer="German Jordanian University",
                    prize="N/A",
                    start_date=local_date(item["start"]),
                    end_date=local_date(item["end"]),
                    location="German Jordanian University, Madaba, Jordan",
                    country="JO",
                    description=description,
                ))
        return events
