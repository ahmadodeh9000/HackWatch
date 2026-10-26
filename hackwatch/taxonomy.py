"""Load taxonomy.yaml and normalise tag lists against it."""
import warnings
from functools import lru_cache
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import yaml

TAXONOMY_PATH = Path(__file__).resolve().parent.parent / "taxonomy.yaml"


@lru_cache(maxsize=None)
def load_taxonomy(path: Path = TAXONOMY_PATH) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def tag_lookup(path: Path = TAXONOMY_PATH) -> Dict[str, str]:
    """Map every accepted spelling (tag id or alias) to its tag id."""
    lookup = {}
    for tag_id, info in (load_taxonomy(path).get("tags") or {}).items():
        lookup[tag_id] = tag_id
        for alias in (info or {}).get("aliases", []):
            lookup[str(alias).lower()] = tag_id
    return lookup


def normalize_tags(tags: Optional[Iterable[str]], strict: bool = False) -> List[str]:
    """Return known tag ids, de-duplicated, in first-seen order.

    Unknown tags raise ValueError when strict (manual YAML), otherwise they're
    dropped with a warning (scraped data).
    """
    if not tags:
        return []
    if isinstance(tags, str):
        tags = [t for t in tags.replace(",", " ").split()]
    lookup = tag_lookup()
    result: List[str] = []
    unknown: List[str] = []
    for raw in tags:
        key = str(raw).strip().lower().replace(" ", "-").replace("_", "-")
        tag = lookup.get(key)
        if tag is None:
            unknown.append(str(raw))
        elif tag not in result:
            result.append(tag)
    if unknown:
        message = f"unknown tag(s) {', '.join(map(repr, unknown))}; allowed tags are listed in taxonomy.yaml"
        if strict:
            raise ValueError(message)
        warnings.warn(message, stacklevel=2)
    return result
