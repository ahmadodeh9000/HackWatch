"""Maps scraper names (as used in sources.yaml) to scraper classes."""
from typing import Dict, Type

SCRAPERS: Dict[str, Type] = {}


def register(name: str):
    """Class decorator: @register("devpost") makes the class available as `scraper: devpost`."""
    def decorator(cls):
        if name in SCRAPERS:
            raise ValueError(f"scraper {name!r} is registered twice")
        cls.name = name
        SCRAPERS[name] = cls
        return cls
    return decorator
