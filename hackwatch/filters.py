import re
from datetime import date, timedelta

JORDAN_RE = re.compile(r"\b(jordan|amman|irbid|aqaba|zarqa|madaba|jerash|karak)\b", re.I)

# Words that mark an event as tech/engineering-related. Matched against title + description.
TECH_TERMS_EN = [
    r"tech\w*", r"ai", r"a\.i\.", r"artificial intelligence", r"machine learning", r"ml", r"llms?",
    r"deep learning", r"data\w*", r"cyber\w*", r"security", r"ctf", r"software", r"devs?",
    r"developers?", r"devops", r"devfest", r"programming", r"cod(e|es|ing|ers?)", r"hack\w*",
    r"datathon", r"ideathon", r"buildathon", r"codefest", r"game jam", r"gam(e|es|ing)", r"gamers?",
    r"robot\w*", r"engineer\w*", r"iot", r"cloud", r"blockchain", r"web3", r"web", r"apps?",
    r"mobile", r"android", r"ios", r"flutter", r"python", r"javascript", r"java", r"linux",
    r"open[- ]source", r"github", r"electronics?", r"embedded", r"pcb", r"arduino", r"raspberry pi",
    r"3d print\w*", r"drones?", r"satellites?", r"space apps", r"nasa", r"stem", r"computing",
    r"computer\w*", r"digital", r"ux", r"ui",
]
TECH_TERMS_AR = [
    "تقني", "تكنولوجيا", "برمج", "ذكاء اصطناعي", "هاكاثون", "روبوت", "سيبراني", "هندس",
    "مطور", "بيانات", "حوسبة", "حاسوب",
]
TECH_RE = re.compile(
    r"\b(" + "|".join(TECH_TERMS_EN) + r")\b|" + "|".join(TECH_TERMS_AR),
    re.I,
)

MAX_DAYS_AHEAD = 365


def _parse(d):
    try:
        return date.fromisoformat(d[:10]) if d else None
    except ValueError:
        return None


def is_in_jordan(event) -> bool:
    country = (event.country or "").upper()
    if country:  # a detected country always wins ("Jordan, MN, US" is not Jordan)
        return country == "JO"
    return bool(JORDAN_RE.search(event.location or ""))


def is_tech_related(event) -> bool:
    return bool(TECH_RE.search(f"{event.title or ''} {event.description or ''}"))


def is_relevant(event, require_tech: bool = False) -> bool:
    """Online/hybrid events from anywhere are kept; in-person events only if they are in Jordan.

    require_tech: also demand a tech keyword. Set per source in sources.yaml
    (require_tech_keywords) for general listings like Eventbrite; sources that
    only list tech/engineering events don't need it.
    """
    if event.source == "manual":
        return True
    if "tbd" in (event.title or "").lower():
        return False
    start = _parse(event.start_date)
    if start and start > date.today() + timedelta(days=MAX_DAYS_AHEAD):
        return False
    if event.mode == "in-person" and not is_in_jordan(event):
        return False
    if require_tech:
        return is_tech_related(event)
    return True
