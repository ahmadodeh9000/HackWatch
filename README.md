# 🔍 HackWatch

**Tech & engineering events in Jordan, on the web, in your calendar and in a weekly digest.**

HackWatch collects hackathons, competitions, conferences, workshops and meetups in Jordan, plus online
events from anywhere (CTFs, Codeforces rounds, online hackathons). In-person events outside Jordan are
left out. It fetches from several sources every day, merges duplicates, and publishes a website, a
calendar feed, a weekly digest and a shareable page per event. Clubs can submit their own events.

![Python 3.12](https://img.shields.io/badge/python-3.12-blue)
![License: MIT](https://img.shields.io/badge/license-MIT-green)

🌐 **Site:** https://ahmadodeh9000.github.io/HackWatch/ (English / العربية) ·
📅 **Calendar feed (Jordan events):** https://ahmadodeh9000.github.io/HackWatch/events.ics ·
📰 **This week's digest:** [digest.txt](https://ahmadodeh9000.github.io/HackWatch/digest.txt) ·
➕ **[Submit an event](https://github.com/ahmadodeh9000/HackWatch/issues/new?template=event.yml)**

---

## ✨ Features

- **Jordan-focused**: in-person events only in Jordan; the site shows Jordan events by default, with a
  toggle for worldwide online events
- **9 sources in the daily run**: GDG chapters, Startup Grind Amman, IEEE Jordan Section, JOSA, GJU,
  Devpost, CTFtime, Codeforces, and community submissions. Eventbrite (Jordan) is off in CI because it
  blocks GitHub's servers; it still runs locally. See [SOURCES.md](SOURCES.md)
- **Deadline first**: each card leads with when registration closes (or when the event starts);
  start/end times in Amman time
- **Types and tags** inferred from titles in English and Arabic and from the sources' own labels
- **Club life hidden by default**: inaugurations, officer kickoffs and awareness days are flagged
  `low_signal`, kept in the data and shown with a toggle
- **Duplicates merged**: the same event from several sources appears once, with all its links
- **Calendar feed** (`events.ics`) for Google, Apple or Outlook calendar
- **Weekly digest** (`digest.txt`), ready to forward to WhatsApp or Telegram, and as an image
  (`digest.png`, 1080×1350, English and Arabic headings) for stories and groups
- **Share pages** (`e/<id>.html`) with Open Graph tags, so a shared link previews nicely
- **Submissions** through a bilingual GitHub issue form (a bot validates it and opens a pull request)
  or a Google Form (imported with `import-form`)
- **Reliable deploys**: per-source fallback to the last good data, "Source down" issues after two
  empty runs, and a check of the live site after every deploy
- **Free to run**: GitHub Actions and Pages only

---

## 🚀 Quick start (CLI)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

python3 -m hackwatch.cli fetch          # fetch every enabled source into hackwatch.db
python3 -m hackwatch.cli list           # upcoming events in a table
```

### Commands

```bash
# Fetch
python3 -m hackwatch.cli fetch                         # all enabled sources
python3 -m hackwatch.cli fetch --source devpost        # one source (even if disabled)

# List and filter (see "Event fields")
python3 -m hackwatch.cli list                          # upcoming
python3 -m hackwatch.cli list --all                    # including past
python3 -m hackwatch.cli list --new                    # first seen in the latest fetch
python3 -m hackwatch.cli list --type competition --tag robotics
python3 -m hackwatch.cli list --mode hybrid --scope jordan

# Add an event to manual_events.yaml
python3 -m hackwatch.cli add                           # prompts for each field
python3 -m hackwatch.cli add -t "Robot Sumo Cup" -u https://example.com/sumo -d 2026-12-05 \
  -l "Irbid, Jordan" -o "IEEE JUST" --type competition --mode in-person --tags robotics,sumo,ieee \
  --start-time 10:00 --end-time 15:00 --deadline 2026-12-01
python3 -m hackwatch.cli add --from-url https://lu.ma/abc123   # pre-filled from the event page, then asks
python3 -m hackwatch.cli add --from-url <url> --yes --dry-run   # show what it found, save nothing
python3 -m hackwatch.cli import-form responses.csv     # Google Form responses (CONTRIBUTING.md)
python3 -m hackwatch.cli validate                      # strict check; exits 1 on any invalid entry

# Weekly digest
python3 -m hackwatch.cli digest --week                 # plain text
python3 -m hackwatch.cli digest --week --format markdown
python3 -m hackwatch.cli digest --png digest.png       # also a 1080x1350 image (English + Arabic headings)

# Everything the site needs (what the deploy runs)
python3 -m hackwatch.cli export --out docs/events.json --labels docs/labels.json \
  --ics docs/events.ics --digest docs/digest.txt --digest-png docs/digest.png --pages docs/e
```

`add --from-url` reads the page's schema.org JSON-LD (Luma, Eventbrite, GDG, Startup Grind…), its
Google Calendar link (IEEE vTools), Open Graph tags, or a Google Form's title and description,
converts times to Amman time, guesses type and tags like the scrapers do, and validates the entry
before saving it. It warns when an event would be hidden (club life) or dropped (in person abroad).

To look at the site locally: `python3 -m http.server 8000 --directory docs`, then open
http://localhost:8000 (`?lang=ar` for Arabic).

### The terminal dashboard (unmaintained)

`python3 hackwatch.py` opens the old interactive terminal menu. **It is no longer maintained**:
it predates times, deadlines, tags, `low_signal`, scope and merged sources, so it shows less than
the site and the CLI, and new features won't be added to it. Use the website or
`python3 -m hackwatch.cli list` instead. It may be removed later.

---

## 🏷️ Event fields

| Field | Values | Notes |
|-------|--------|-------|
| `type` | `hackathon`, `competition`, `conference`, `workshop`, `meetup`, `other` | `contest` is accepted as `competition`. Unknown or missing → `other`. |
| `mode` | `in-person`, `online`, `hybrid` | Default comes from the location (`Online` → `online`). |
| `tags` | ids from [`taxonomy.yaml`](taxonomy.yaml), e.g. `ai`, `ctf`, `cp`, `robotics`, `sumo`, `ieee` | Aliases work (`cybersecurity` → `security`). Unknown tags are an error in `manual_events.yaml`. Each tag has an English and an Arabic label. |
| `scope` | `jordan`, `worldwide` | Set per source in `sources.yaml`; can be overridden per event. |
| `start_time`, `end_time` | `HH:MM`, Amman time, 24 h | Optional. Without them the event is all-day in the calendar. |
| `registration_deadline` | `YYYY-MM-DD` | Optional; on or before the last day of the event. |
| `low_signal` | `true` / `false` | Club life (title matches a `low_signal` keyword in `taxonomy.yaml`). Hidden on the site unless toggled, left out of the calendar feed and the digest. |
| `cost`, `certificate`, `open_to` | `free`/`paid`; `true`/`false`; `anyone`/`students`/`members` | Optional; unknown = not shown. GDG/Startup Grind fill `cost` from the ticket price. Asked (optional) on both forms. |
| `stale` | `true` / `false` | The source returned nothing this run, so this is the last deployed copy (dropped after 7 days). |

**Export-only fields** in `events.json`: `display_title` (ALL-CAPS titles in title case, for
display; `title` stays as the source wrote it), `city` (amman, irbid, zarqa, aqaba, salt; for the
site's city filter), and for a weekly series (same source, title and organiser, whole weeks apart)
`recurrence: weekly`, `sessions` and `series_until`, with the record's dates being the next session.
Each card also gets `e/<id>.ics` for "Add to calendar".

**Inference.** When a source doesn't set `type` or `tags`, they are guessed from the title, the
source's own labels and the description, using the English and Arabic rules in
[`taxonomy.yaml`](taxonomy.yaml). Precedence for type: explicit → inferred → the source's
`default_type` → `other`. A source's `default_tags` are always added.

**Pinned filter chips.** The site always shows the types and tags listed under `pinned:` in
`taxonomy.yaml` (with a count, faded at 0); other values appear only when events use them.

---

## 📁 Project structure

```
HackWatch/
├── docs/                     ← The website (GitHub Pages); data files are generated on deploy
├── manual_events.yaml        ← Community and hand-added events
├── sources.yaml              ← Which sources run, their scope, defaults and options
├── taxonomy.yaml             ← Tags (EN/AR labels, aliases), inference rules, pinned chips, low_signal
├── SOURCES.md                ← Status of every source, tried and failed ones too
├── CONTRIBUTING.md           ← Submitting events, the Google Form, adding a source
├── hackwatch.py              ← Old terminal dashboard (unmaintained)
├── scripts/                  ← Fixture recorder, export/live checks, issue → event, runner probe
├── tests/                    ← pytest suite (offline, recorded fixtures)
└── hackwatch/
    ├── cli.py                ← Typer CLI commands
    ├── models.py             ← Event dataclass, type/mode/scope values
    ├── db.py                 ← SQLite: per-source observations → merged events
    ├── dedup.py              ← Which listings are the same event
    ├── filters.py            ← Which events are kept (Jordan / online / tech)
    ├── infer.py, taxonomy.py ← Type/tag inference, taxonomy loading
    ├── carryover.py          ← Keep a silent source's last deployed events (stale)
    ├── health.py             ← "Source down" issues
    ├── ics.py, digest.py, pages.py ← Calendar feed, weekly digest, share pages
    ├── submissions.py, formimport.py ← Shared validation for the issue form and Google Form
    ├── timeutil.py           ← Source timestamps → Amman dates and times
    └── scrapers/             ← One module per source type (bevy, vtools, gju, josa, ...)
```

---

## 🔁 How the daily update works

The `Update HackWatch Events & Deploy` workflow runs every day at 03:00 UTC, on every push to
`main`, and by hand:

1. Runs the tests, then fetches every enabled source in `sources.yaml` and writes a per-source
   report (`status.json`, also in the job summary).
2. `health` counts empty runs per source; after 2 in a row it opens a "Source down: <name>" issue,
   and closes it when the source recovers.
3. Each source that fetched replaces what it listed before, so removed events disappear. A source
   that had events on the live site but returned nothing now keeps them, marked stale, for up to 7 days.
4. Listings of the same event are merged (same link, or a similar title within a day from another
   source); precedence is manual > Jordan sources > worldwide feeds.
5. Exports `events.json`, `labels.json`, `events.ics`, `digest.txt`, `digest.png` and `e/<id>.html`, and refuses
   to deploy if there are 0 events or fewer than half of what's live (run it by hand with **force**
   after an expected big drop).
6. Deploys to Pages, then fetches the live `events.json` and `events.ics` and fails if they're
   missing or empty.

## 🔧 Adding a source

See [CONTRIBUTING.md](CONTRIBUTING.md#2-add-a-source-scraper). In short: a `BaseScraper` subclass
registered by name, an entry in `sources.yaml`, recorded fixtures and offline tests. Read
[SOURCES.md](SOURCES.md) first; check the site's `robots.txt` and test it from the GitHub runner.

```python
from hackwatch.models import Event
from hackwatch.scrapers.base import BaseScraper
from hackwatch.scrapers.registry import register


@register("mysource")
class MySourceScraper(BaseScraper):
    def __init__(self, url: str, delay_seconds: float = 2.0):
        super().__init__(delay_seconds=delay_seconds)
        self.url = url

    def fetch(self) -> list[Event]:
        resp = self.get(self.url)  # rate-limited, honest User-Agent
        return [Event(title="...", url="...", source=self.name)]
```

---

## 📦 Dependencies

| Package | Purpose |
|---------|---------|
| `requests` | HTTP requests for scrapers |
| `beautifulsoup4` | HTML parsing |
| `pyyaml` | YAML files |
| `typer` | CLI |
| `rich` | Terminal tables |
| `Pillow` | `digest.png` (Arabic needs libraqm + FriBiDi; the deploy job installs them) |

## 📄 License

MIT. Happy hacking! 🚀
