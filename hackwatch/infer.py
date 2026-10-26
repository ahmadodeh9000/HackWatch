"""Guess an event's type and tags from its text, using the rules in taxonomy.yaml.

Inputs, in order of trust: the title, the source's own labels (GDG event tags,
Devpost themes), then the description. Values set explicitly by a source or
in manual_events.yaml are never overridden; see apply_defaults.
"""
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Iterable, List, Optional, Pattern, Tuple

from hackwatch.models import VALID_EVENT_TYPES, Event
from hackwatch.taxonomy import load_taxonomy

ARABIC_RE = re.compile(r"[؀-ۿ]")


@dataclass
class Rule:
    value: str              # the type or tag this rule gives
    pattern: Optional[Pattern]  # matches keywords in free text
    labels: frozenset       # exact (lower-cased) source labels


def keyword_pattern(keywords: Iterable[str]) -> Optional[Pattern]:
    """One regex for a list of keywords.

    English: whole words/phrases, optional plural s ("hack" matches "Hacks",
    not "Lifehacks"). Arabic: anywhere, since prefixes like ال attach to words.
    """
    parts = []
    for kw in keywords:
        kw = str(kw).strip().lower()
        if not kw:
            continue
        escaped = re.escape(kw).replace(r"\ ", r"[\s\-]+")  # "hack day" also matches "hack-day"
        if ARABIC_RE.search(kw):
            parts.append(escaped)
        else:
            parts.append(rf"(?<!\w){escaped}(?:s|es)?(?!\w)")
    return re.compile("|".join(parts), re.I) if parts else None


def _rule(value: str, info: dict) -> Rule:
    return Rule(
        value=value,
        pattern=keyword_pattern(info.get("keywords") or []),
        labels=frozenset(str(l).strip().lower() for l in info.get("labels") or []),
    )


@lru_cache(maxsize=None)
def type_rules() -> Tuple[Rule, ...]:
    return tuple(_rule(r["type"], r) for r in load_taxonomy().get("types") or [])


@lru_cache(maxsize=None)
def tag_rules() -> Tuple[Rule, ...]:
    return tuple(_rule(tag, info or {}) for tag, info in (load_taxonomy().get("tags") or {}).items())


def _matches(rule: Rule, text: str = "", labels: Iterable[str] = ()) -> bool:
    if text and rule.pattern and rule.pattern.search(text):
        return True
    return any(label.strip().lower() in rule.labels for label in labels)


def infer_type(event: Event, allowed: Optional[Iterable[str]] = None) -> Optional[str]:
    """First matching type rule, trying title, then labels, then description.

    `allowed` restricts the result (e.g. Devpost only lists hackathons and
    competitions, so "Syntax Summit" there is not a conference).
    """
    allowed = set(allowed) if allowed else set(VALID_EVENT_TYPES)
    labels = list(event.source_labels or [])
    fields = [
        (event.title or "", []),
        # Labels match exactly, and also as text ("Workshop / hands-on session" contains "workshop").
        (" | ".join(labels), labels),
        (event.description or "", []),
    ]
    for text, field_labels in fields:
        for rule in type_rules():
            if rule.value in allowed and _matches(rule, text, field_labels):
                return rule.value
    return None


def infer_tags(event: Event) -> List[str]:
    """Every tag whose rule matches the title, labels or description, in taxonomy order."""
    labels = list(event.source_labels or [])
    text = " | ".join([event.title or "", *labels, event.description or ""])
    return [rule.value for rule in tag_rules() if _matches(rule, text, labels)]


def apply_defaults(event: Event, default_type: Optional[str] = None, default_tags: Iterable[str] = (),
                   default_scope: Optional[str] = None, allowed_types: Optional[Iterable[str]] = None,
                   infer_tags_from_text: bool = True) -> Event:
    """Fill in what the source didn't set.

    type:  explicit > inferred > source default (> 'other' when stored)
    tags:  explicit, or else inferred (unless the source turns that off);
           source default tags are always added
    scope: explicit > source default (> derived from location when stored)
    """
    if event.type is None:
        event.type = infer_type(event, allowed_types) or default_type
    if not event.tags and infer_tags_from_text:
        event.tags = infer_tags(event)
    event.tags = event.tags + [t for t in default_tags if t not in event.tags]
    if event.scope is None:
        event.scope = default_scope
    return event
