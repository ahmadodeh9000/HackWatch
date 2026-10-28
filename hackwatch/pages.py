"""One small HTML page per event (docs/e/<id>.html) for sharing.

Each page has Open Graph / Twitter tags so a link pasted in WhatsApp, X or LinkedIn
previews with the title, date, place and type. Visitors get the essentials, a button
to the organiser's page and a link back to the list. Ids are the merged event id
(a hash of the normalised URL), so they're the same every run.
"""
import html
from datetime import date
from pathlib import Path
from typing import Iterable

from hackwatch.digest import SITE_URL, event_page_url
from hackwatch.models import Event
from hackwatch.ics import build_calendar
from hackwatch.tidy import shown_title

TYPE_LABELS = {"hackathon": "Hackathon", "competition": "Competition", "conference": "Conference",
               "workshop": "Workshop", "meetup": "Meetup", "other": "Event"}


def summary_line(e: Event) -> str:
    """'Sat 28 Nov 2026, 11:00 · King Hussein Business Park, Amman · Conference'."""
    parts = []
    if e.start_date:
        d = date.fromisoformat(e.start_date[:10])
        when = d.strftime("%a %-d %b %Y")
        if e.end_date and e.end_date != e.start_date:
            when += " – " + date.fromisoformat(e.end_date[:10]).strftime("%a %-d %b")
        if e.start_time:
            when += f", {e.start_time}"
        parts.append(when)
    parts.append("Online" if e.mode == "online" else (e.location or "Location TBA").replace(", Jordan", ""))
    parts.append(TYPE_LABELS.get(e.type or "other", "Event"))
    return " · ".join(parts)


def render_page(e: Event, site: str = SITE_URL) -> str:
    esc = lambda s: html.escape(str(s or ""), quote=True)  # noqa: E731
    url = event_page_url(e, site)
    line = summary_line(e)
    title = shown_title(e)
    description = " ".join((e.description or "").split())
    teaser = (description[:157] + "…") if len(description) > 160 else description
    og_description = f"{line}. {teaser}" if teaser else line
    deadline = (f'<p class="deadline">Registration closes {esc(date.fromisoformat(e.registration_deadline[:10]).strftime("%a %-d %b %Y"))}</p>'
                if e.registration_deadline else "")
    target = e.url if str(e.url).startswith(("http://", "https://")) else site
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)} · HackWatch</title>
<meta name="description" content="{esc(og_description)}">
<link rel="canonical" href="{esc(url)}">
<meta property="og:type" content="website">
<meta property="og:site_name" content="HackWatch: tech &amp; engineering events in Jordan">
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(og_description)}">
<meta property="og:url" content="{esc(url)}">
<meta property="og:image" content="{esc(site.rstrip('/'))}/og.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{esc(title)}">
<meta name="twitter:description" content="{esc(og_description)}">
<meta name="twitter:image" content="{esc(site.rstrip('/'))}/og.png">
<style>
:root{{--bg:#faf8f5;--surface:#fff;--text:#1f2430;--muted:#5d6475;--border:#e8e3db;--accent:#4f46e5;--accent-ink:#fff}}
@media (prefers-color-scheme:dark){{:root{{--bg:#15161c;--surface:#1e2029;--text:#eceef4;--muted:#a3a9ba;--border:#2c2f3b;--accent:#8b85ff;--accent-ink:#12121a}}}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font:16px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}}
main{{max-width:640px;margin:0 auto;padding:32px 16px}}
.card{{background:var(--surface);border:1px solid var(--border);border-radius:16px;padding:24px}}
h1{{font-size:1.5rem;line-height:1.25;margin:0 0 8px;overflow-wrap:anywhere}}
.meta,.org,.deadline{{color:var(--muted);margin:0 0 8px}}.deadline{{font-weight:600}}
p.desc{{margin:16px 0;overflow-wrap:anywhere}}
.btn{{display:inline-block;margin-top:8px;padding:12px 22px;border-radius:999px;background:var(--accent);color:var(--accent-ink);font-weight:600;text-decoration:none}}
.back{{display:inline-block;margin-top:20px;color:var(--accent)}}
:focus-visible{{outline:3px solid var(--accent);outline-offset:2px;border-radius:8px}}
</style>
</head>
<body>
<main>
  <article class="card">
    <h1>{esc(title)}</h1>
    <p class="meta">{esc(line)}</p>
    {f'<p class="org">by {esc(e.organizer)}</p>' if e.organizer else ''}
    {deadline}
    {f'<p class="desc">{esc(description[:600])}</p>' if description else ''}
    <a class="btn" href="{esc(target)}" rel="noopener">Go to the event page →</a>
  </article>
  <a class="back" href="{esc(site)}">← All tech &amp; engineering events in Jordan</a>
</main>
</body>
</html>
"""


def write_calendar_files(items: Iterable[dict], out_dir: Path) -> int:
    """e/<id>.ics per card, for "Add to calendar" (all upcoming sessions for a series).

    `items` are series.merge_series() results; old files are replaced.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("*.ics"):
        old.unlink()
    count = 0
    for item in items:
        e = item["event"]
        if e.id and e.start_date:
            body = build_calendar(item.get("members") or [e], name=None)
            (out_dir / f"{e.id}.ics").write_text(body, encoding="utf-8", newline="")
            count += 1
    return count


def write_pages(events: Iterable[Event], out_dir: Path, site: str = SITE_URL) -> int:
    """Write one page per event into out_dir (replacing pages from earlier runs)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("*.html"):
        old.unlink()
    count = 0
    for e in events:
        if e.id:
            (out_dir / f"{e.id}.html").write_text(render_page(e, site), encoding="utf-8")
            count += 1
    return count
