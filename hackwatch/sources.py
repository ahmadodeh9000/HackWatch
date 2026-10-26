"""Load sources.yaml and build the configured scrapers."""
import inspect
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from hackwatch.models import validate_event_type, validate_scope
from hackwatch.scrapers.base import BaseScraper
from hackwatch.scrapers.registry import SCRAPERS
from hackwatch.taxonomy import normalize_tags

SOURCES_PATH = Path(__file__).resolve().parent.parent / "sources.yaml"
ALLOWED_KEYS = {"name", "scraper", "enabled", "scope", "default_type", "default_tags", "allowed_types",
                "require_tech_keywords", "options"}


@dataclass
class SourceConfig:
    name: str
    scraper: str
    enabled: bool
    scope: str
    default_type: Optional[str] = None
    default_tags: List[str] = field(default_factory=list)
    allowed_types: Optional[List[str]] = None
    require_tech_keywords: bool = False
    options: Dict[str, Any] = field(default_factory=dict)


def parse_source(raw: dict) -> SourceConfig:
    """Validate one sources.yaml entry; raises ValueError naming the problem."""
    if not isinstance(raw, dict) or not raw.get("name"):
        raise ValueError(f"each source needs a name, got {raw!r}")
    name = raw["name"]
    unknown = set(raw) - ALLOWED_KEYS
    if unknown:
        raise ValueError(f"source {name!r}: unknown key(s) {', '.join(sorted(unknown))}")
    scraper = raw.get("scraper", name)
    if scraper not in SCRAPERS:
        raise ValueError(f"source {name!r}: no scraper called {scraper!r} (known: {', '.join(sorted(SCRAPERS))})")
    if "scope" not in raw:
        raise ValueError(f"source {name!r}: scope is required (jordan or worldwide)")
    try:
        return SourceConfig(
            name=name,
            scraper=scraper,
            enabled=bool(raw.get("enabled", True)),
            scope=validate_scope(raw["scope"]),
            default_type=validate_event_type(raw["default_type"], strict=True) if raw.get("default_type") else None,
            default_tags=normalize_tags(raw.get("default_tags"), strict=True),
            allowed_types=[validate_event_type(t, strict=True) for t in raw["allowed_types"]]
            if raw.get("allowed_types") else None,
            require_tech_keywords=bool(raw.get("require_tech_keywords", False)),
            options=dict(raw.get("options") or {}),
        )
    except ValueError as exc:
        raise ValueError(f"source {name!r}: {exc}") from None


def load_sources(path: Path = SOURCES_PATH) -> List[SourceConfig]:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    configs = [parse_source(raw) for raw in data.get("sources") or []]
    names = [c.name for c in configs]
    duplicates = {n for n in names if names.count(n) > 1}
    if duplicates:
        raise ValueError(f"duplicate source name(s) in {path}: {', '.join(sorted(duplicates))}")
    return configs


def build_scraper(config: SourceConfig) -> BaseScraper:
    """Instantiate the scraper with its options and attach the source defaults."""
    cls = SCRAPERS[config.scraper]
    accepted = set(inspect.signature(cls.__init__).parameters) - {"self"}
    unknown = set(config.options) - accepted
    if unknown:
        raise ValueError(f"source {config.name!r}: unknown option(s) {', '.join(sorted(unknown))} "
                         f"for scraper {config.scraper!r} (accepted: {', '.join(sorted(accepted))})")
    try:
        scraper = cls(**config.options)
    except ValueError as exc:
        raise ValueError(f"source {config.name!r}: {exc}") from None
    scraper.name = config.name
    scraper.default_scope = config.scope
    scraper.default_type = config.default_type
    scraper.default_tags = list(config.default_tags)
    scraper.allowed_types = config.allowed_types
    scraper.require_tech_keywords = config.require_tech_keywords
    return scraper


def build_scrapers(path: Path = SOURCES_PATH, include_disabled: bool = False) -> List[BaseScraper]:
    return [build_scraper(c) for c in load_sources(path) if c.enabled or include_disabled]
