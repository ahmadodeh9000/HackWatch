try:
    import pycountry
except ImportError:
    pycountry = None


def to_iso2(text):
    """'Miami, United States of America' -> 'US'; 'Amman, JO' -> 'JO'; 'Online' -> None."""
    if not text or pycountry is None:
        return None
    for part in reversed([p.strip() for p in text.split(",")]):
        try:
            return pycountry.countries.lookup(part).alpha_2
        except LookupError:
            continue
    return None
