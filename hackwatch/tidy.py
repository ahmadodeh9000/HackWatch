"""Small text clean-ups: junk location parts, and ALL-CAPS titles for display.

- clean_location() runs before an event is stored (db._prepare). vTools has a free-text
  "building" field that branches fill with a room or block letter, giving "E, Amman, Jordan".
- display_title() leaves the stored title alone; the export adds it as `display_title`
  when it differs, and the site, digest, share pages and calendar show that.
"""
import re
from typing import Optional

from hackwatch.models import Event

JUNK_PARTS = {"tba", "tbd", "n/a", "na", "none", "-", "null", "online event"}

# Kept in capitals when a title is converted. Words without vowels (MCC, PSUT's "SB") and
# words with digits or & + (PES&IAS, 3D, W3C) are kept as well, without being listed.
ACRONYMS = {
    "IEEE", "GDG", "AI", "ML", "IOT", "CTF", "UX", "UI", "AR", "VR", "XR", "GJU", "PSUT", "JUST", "HTU",
    "BAU", "JOSA", "NASA", "API", "APIS", "WIE", "RAS", "CIS", "PES", "IAS", "UJ", "ZU", "YU", "AAU",
    "MEU", "ASU", "CS", "EMBS", "STEM", "UN", "UAE", "KSA", "ICPC", "ACM", "JCPC", "AWS", "GCP", "SQL",
    "HTML", "CSS", "PCB", "UAV", "GIS", "IT", "ICT", "NLP", "LLM", "LLMS", "GPT", "ROS", "IOS", "MENA",
    "ZINC", "KHBP", "AQ", "IEEE-HKN", "HKN",
}
SMALL_WORDS = {"a", "an", "and", "as", "at", "by", "for", "from", "in", "into", "of", "on", "or",
               "the", "to", "vs", "with"}
WORD = re.compile(r"[A-Za-z][A-Za-z'&+0-9]*")
VOWELS = set("AEIOUY")


def clean_location(location: Optional[str]) -> Optional[str]:
    """'E, Amman, Jordan' -> 'Amman, Jordan'; drops 1–2 letter parts, numbers, TBA, repeats."""
    if not location:
        return location
    parts, seen = [], set()
    for raw in location.split(","):
        part = " ".join(raw.split()).strip(" -–")
        key = part.lower()
        if not part or key in JUNK_PARTS or key in seen:
            continue
        if part.isdigit() or (len(part) <= 2 and part.isascii()):
            continue  # building letters ("E"), room numbers, postcodes
        seen.add(key)
        parts.append(part)
    # "Jordan, Yarmouk University, Irbid, Jordan" -> country last.
    if "jordan" in seen and len(parts) > 1:
        parts = [p for p in parts if p.lower() != "jordan"] + ["Jordan"]
    return ", ".join(parts) or location


def is_all_caps(title: str) -> bool:
    """Mostly shouting: every cased word is in capitals, with real words among them.

    "IEEE PES&IAS MEETING" yes; "PINK+ CTF 2026" no (a name, not a sentence).
    """
    words = WORD.findall(title or "")
    if not words or any(w != w.upper() for w in words):
        return False
    long_words = [w for w in words if len(w) >= 4 and w not in ACRONYMS and w.isalpha()]
    return len(long_words) >= 2 or (len(long_words) == 1 and len(words) >= 3)


def _word_case(word: str, first: bool) -> str:
    def one(part: str, first_part: bool) -> str:
        if not part:
            return part
        if part in ACRONYMS or not (set(part) & VOWELS) or re.search(r"[0-9&+]", part):
            return part
        low = part.lower()
        if not first_part and low in SMALL_WORDS:
            return low
        return low[0].upper() + low[1:]
    pieces = word.split("-")
    return "-".join(one(p, first and i == 0) for i, p in enumerate(pieces))


def display_title(title: str) -> str:
    """'MCC ROBOTICS ON PROESTHICS WORKSHOP' -> 'MCC Robotics on Proesthics Workshop'."""
    if not is_all_caps(title):
        return title
    out, first = [], True
    for token in title.split(" "):
        if WORD.search(token):
            out.append(re.sub(r"[A-Za-z][A-Za-z'&+0-9-]*", lambda m: _word_case(m.group(0), first), token))
            first = False
        else:
            out.append(token)
    return " ".join(out)


def shown_title(event: Event) -> str:
    return display_title(event.title or "")
