import re
from datetime import datetime
from typing import List, Optional, Tuple
from bs4 import BeautifulSoup

from hackwatch.models import Event
from hackwatch.scrapers.base import BaseScraper
from hackwatch.scrapers.registry import register


def parse_devpost_dates(date_str: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """Parse Devpost date ranges like 'Aug 31 - Oct 23, 2026' into ISO (YYYY-MM-DD)."""
    if not date_str:
        return None, None

    parts = [p.strip() for p in date_str.split(" - ")]
    date_formats = ["%b %d, %Y", "%b %d %Y", "%B %d, %Y", "%Y-%m-%d"]

    if len(parts) == 1:
        for fmt in date_formats:
            try:
                dt = datetime.strptime(parts[0], fmt)
                iso = dt.strftime("%Y-%m-%d")
                return iso, iso
            except ValueError:
                pass
        return None, None

    end_str = parts[1]
    start_str = parts[0]
    end_dt = None

    for fmt in date_formats:
        try:
            end_dt = datetime.strptime(end_str, fmt)
            break
        except ValueError:
            pass

    if not end_dt and start_str:
        month = start_str.split()[0]
        for fmt in date_formats:
            try:
                end_dt = datetime.strptime(f"{month} {end_str}", fmt)
                break
            except ValueError:
                pass

    if not end_dt:
        return None, None

    end_iso = end_dt.strftime("%Y-%m-%d")

    # Try parsing start with full format first
    for fmt in date_formats:
        try:
            start_dt = datetime.strptime(start_str, fmt)
            return start_dt.strftime("%Y-%m-%d"), end_iso
        except ValueError:
            pass

    # Try attaching end_dt's year
    for fmt in ["%b %d, %Y", "%B %d, %Y"]:
        try:
            start_dt = datetime.strptime(f"{start_str}, {end_dt.year}", fmt)
            if start_dt > end_dt:
                start_dt = start_dt.replace(year=end_dt.year - 1)
            return start_dt.strftime("%Y-%m-%d"), end_iso
        except ValueError:
            pass

    return None, end_iso


def extract_devpost_prize(item: dict) -> str:
    """Extract prize amount from item, title, or non-cash counts. Fallback to N/A."""
    title = item.get("title", "")
    prize_raw = item.get("prize_amount")
    prize = None
    if prize_raw:
        prize = BeautifulSoup(str(prize_raw), "html.parser").get_text(strip=True)

    clean_num = re.sub(r"[^\d]", "", prize or "")
    is_zero_or_empty = (not clean_num or clean_num == "0" or prize == "$0")

    # Extract prize mentioned in title, e.g. ($100k+ in prizes!) or ($40,000 in prizes)
    title_match = re.search(r"\(([\$€£][0-9kKmM\+,\.]+(?:\s*(?:in\s*)?prizes?)?[^\)]*)\)", title, re.IGNORECASE)
    if not title_match:
        title_match = re.search(r"([\$€£][0-9kKmM\+,\.]+\+?(?:\s+in\s+prizes)?)", title, re.IGNORECASE)

    if is_zero_or_empty:
        if title_match:
            return title_match.group(1).rstrip("! ")
        prizes_counts = item.get("prizes_counts")
        other_prizes = prizes_counts.get("other", 0) if isinstance(prizes_counts, dict) else 0
        if other_prizes > 0:
            return f"{other_prizes} non-cash prize(s)"
        return "N/A"

    return prize if prize else "N/A"


@register("devpost")
class DevpostScraper(BaseScraper):
    def __init__(self, max_pages: int = 2, delay_seconds: float = 2.0):
        super().__init__(delay_seconds=delay_seconds)
        self.max_pages = max_pages
        self.api_url = "https://devpost.com/api/hackathons"

    def fetch(self) -> List[Event]:
        events: List[Event] = []

        for page in range(1, self.max_pages + 1):
            params = {
                "status[]": ["upcoming", "open"],
                "page": page
            }
            resp = self.get(self.api_url, params=params)
            data = resp.json()
            hackathons = data.get("hackathons", [])
            if not hackathons:
                break

            for item in hackathons:
                title = item.get("title")
                url = item.get("url")
                if not title or not url:
                    continue

                prize = extract_devpost_prize(item)
                organizer = item.get("organization_name")

                # Location & Online status
                loc_data = item.get("displayed_location")
                location = None
                is_online = False
                if isinstance(loc_data, dict):
                    location = loc_data.get("location")
                elif isinstance(loc_data, str):
                    location = loc_data

                if location and "online" in location.lower():
                    is_online = True

                # Dates
                dates_raw = item.get("submission_period_dates")
                start_date, end_date = parse_devpost_dates(dates_raw)
                registration_deadline = end_date

                # Themes / Description
                themes = [t.get("name") for t in item.get("themes", []) if isinstance(t, dict) and t.get("name")]
                description = f"Themes: {', '.join(themes)}" if themes else None

                event = Event(
                    title=title,
                    url=url,
                    source=self.name,
                    organizer=organizer,
                    prize=prize,
                    registration_deadline=registration_deadline,
                    start_date=start_date,
                    end_date=end_date,
                    location=location,
                    is_online=is_online,
                    description=description,
                    source_labels=themes,
                )
                events.append(event)

        return events

