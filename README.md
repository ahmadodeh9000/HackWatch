# 🔍 HackWatch

**Tech & engineering events in Jordan: on the web, in your calendar and in your terminal.**

HackWatch collects hackathons, competitions, conferences, workshops and meetups in Jordan, plus online
events from anywhere (CTFs, Codeforces rounds, online hackathons). In-person events outside Jordan are
left out. It fetches from several sources daily, merges duplicates, and publishes a website and a
calendar feed. Clubs can submit their own events through a short bilingual form.

![Python 3.12](https://img.shields.io/badge/python-3.12-blue)
![License: MIT](https://img.shields.io/badge/license-MIT-green)

🌐 **Live site:** https://ahmadodeh9000.github.io/HackWatch/ ·
📅 **Calendar feed (Jordan events):** https://ahmadodeh9000.github.io/HackWatch/events.ics ·
➕ **[Submit an event](https://github.com/ahmadodeh9000/HackWatch/issues/new?template=event.yml)**

---

## ✨ Features

- **Jordan-focused** — In-person events only in Jordan; the site shows Jordan events by default, with a toggle for worldwide online events
- **8 sources** — GDG chapters, IEEE Jordan Section, JOSA, Eventbrite (Jordan), Devpost, CTFtime, Codeforces, and community submissions; see [SOURCES.md](SOURCES.md)
- **Types, tags and modes** — Inferred from titles (English and Arabic) and the sources' own labels
- **Duplicates merged** — The same event from several sources appears once, with all its links
- **Calendar feed** — Subscribe to `events.ics` in Google/Apple/Outlook calendar
- **Community submissions** — A bilingual issue form; a bot validates it and opens a pull request
- **Interactive dashboard** — Rich terminal UI with color-coded sources, urgency indicators, and event details
- **Smart date handling** — Events sorted by date, past events hidden by default, countdown indicators
- **Local-first** — All data stored in a single `hackwatch.db` SQLite file
- **Manual events** — Add your own events via YAML, the CLI, or the [issue form](CONTRIBUTING.md)
- **Search** — Full-text keyword search across titles, organizers, locations, and descriptions
- **CLI commands** — Also supports traditional CLI via `python3 -m hackwatch.cli`

---

## 🚀 Quick Start

### 1. Make a Virtual Environment 

```bash
python3 -m venv venv
```

### 2. Activate it

```bash
source venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Launch the interactive dashboard

```bash
python3 hackwatch.py
```

That's it! You'll see a menu like this:

```
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃                   Main Menu                      ┃
┣━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┫
┃  1  📋  Browse Events                            ┃
┃  2  🔄  Fetch New Events                         ┃
┃  3  🆕  Show New Events                          ┃
┃  4  📊  Dashboard                                ┃
┃  5  ➕  Add Manual Event                         ┃
┃  6  🔍  Search Events                            ┃
┃  0  🚪  Exit                                     ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
```

---

## 📖 Usage

### Interactive Mode (recommended)

```bash
python3 hackwatch.py
```

| Option | Description |
|--------|-------------|
| **1 — Browse Events** | View all upcoming events in a formatted table. Enter a number to see full details. Press `a` to include past events. |
| **2 — Fetch New Events** | Scrape all sources and store/update events in the database. |
| **3 — Show New Events** | Display only events first discovered in the latest fetch. |
| **4 — Dashboard** | Quick stats: total events, upcoming count, this week, new since last fetch, and source breakdown. |
| **5 — Add Manual Event** | Interactively add an event to `manual_events.yaml`. |
| **6 — Search Events** | Search by keyword across all event fields. |

### CLI Mode

```bash
# Fetch events from all sources
python3 -m hackwatch.cli fetch

# Fetch from a specific source
python3 -m hackwatch.cli fetch --source devpost

# List upcoming events
python3 -m hackwatch.cli list

# List all events (including past)
python3 -m hackwatch.cli list --all

# Show only new events from last fetch
python3 -m hackwatch.cli list --new

# Filter by type, tag, mode or scope (see "Event fields" below)
python3 -m hackwatch.cli list --type competition --tag robotics
python3 -m hackwatch.cli list --mode hybrid --scope jordan

# Add a manual event interactively
python3 -m hackwatch.cli add

# ...or with flags
python3 -m hackwatch.cli add -t "Robot Sumo Cup" -u https://example.com/sumo -d 2026-12-05 \
  -l "Irbid, Jordan" -o "IEEE JUST" --type competition --mode in-person --tags robotics,sumo,ieee

# Check manual_events.yaml strictly (exits 1 on any invalid entry)
python3 -m hackwatch.cli validate

# Export upcoming events to JSON, plus tag labels and the calendar feed for the site
python3 -m hackwatch.cli export --out docs/events.json --labels docs/labels.json --ics docs/events.ics
```

---

## 🏷️ Event fields

| Field | Values | Notes |
|-------|--------|-------|
| `type` | `hackathon`, `competition`, `conference`, `workshop`, `meetup`, `other` | `contest` is accepted as `competition`. Unknown or missing → `other`. Devpost events default to `hackathon`. |
| `mode` | `in-person`, `online`, `hybrid` | Default comes from the location (`Online` → `online`). Hybrid events count as online for filtering. |
| `tags` | ids from [`taxonomy.yaml`](taxonomy.yaml), e.g. `ai`, `ctf`, `cp`, `robotics`, `sumo`, `ieee` | Aliases work (`cybersecurity` → `security`). Unknown tags are an error in `manual_events.yaml`. |
| `scope` | `jordan`, `worldwide` | Set per source (Devpost: worldwide; Eventbrite, GDG, JOSA, manual: jordan). Can be overridden per event. |

**Inference.** When a source doesn't set `type` or `tags`, they are guessed from the title,
the source's own labels (GDG event tags, Devpost themes) and the description, using the
English and Arabic keyword rules in [`taxonomy.yaml`](taxonomy.yaml). Order of precedence for
type: explicit value → inferred → the source's `default_type` in `sources.yaml` → `other`.
Explicit tags are kept as they are; a source's `default_tags` are always added.

The JSON export still includes the old `is_online` flag (`true` for online and hybrid) so older versions of the site keep working.

---

## 📁 Project Structure

```
HackWatch/
├── hackwatch.py              ← Interactive dashboard entry point
├── requirements.txt          ← Python dependencies
├── manual_events.yaml        ← Manually added events (YAML)
├── sources.yaml              ← Which sources run, their scope/defaults/options
├── taxonomy.yaml             ← Allowed event tags and their aliases
├── SOURCES.md                ← Status of every event source
├── scripts/                  ← Fixture recorder, CI export check
├── tests/                    ← pytest suite (offline, recorded fixtures)
├── hackwatch.db              ← SQLite database (auto-created)
└── hackwatch/
    ├── __init__.py
    ├── cli.py                ← Typer CLI commands
    ├── models.py             ← Event dataclass, type/mode/scope values
    ├── taxonomy.py           ← Loads taxonomy.yaml, normalises tags
    ├── filters.py            ← Which events are kept (Jordan / tech)
    ├── sources.py            ← Loads sources.yaml, builds scrapers
    ├── db.py                 ← SQLite database layer
    └── scrapers/
        ├── __init__.py
        ├── base.py           ← BaseScraper (rate-limited HTTP)
        ├── registry.py       ← @register("name") scraper registry
        ├── devpost.py        ← Devpost API scraper
        ├── eventbrite.py     ← Eventbrite LD+JSON scraper
        ├── gdg.py            ← Google Developer Groups API
        ├── josa.py           ← JOSA events page scraper
        └── manual.py         ← YAML file reader
```

---

## 🔁 How the daily update works

The `Update HackWatch Events & Deploy` workflow runs every day (and on manual runs):

1. Runs the tests, then fetches every enabled source in `sources.yaml`.
2. Each source that fetched successfully replaces what it listed before, so cancelled or removed
   events disappear. A source that errors keeps its old events.
3. Listings of the same event are merged (same link, or a similar title within a day from another source);
   precedence is manual > Jordan sources > worldwide feeds.
4. Exports `events.json`, `labels.json` and `events.ics`, and refuses to deploy if there are 0 events or
   fewer than half of what's live. Run it manually with **force** after an expected big drop.

## 🔧 Adding a New Scraper

1. Create `hackwatch/scrapers/mysource.py` with a `BaseScraper` subclass, registered by name.
   Constructor arguments become the source's `options` in `sources.yaml`.
2. Import the module in `hackwatch/scrapers/__init__.py` so it registers.
3. Add an entry to [`sources.yaml`](sources.yaml) with its `scope` and any `default_type`, `default_tags` and `options`.
4. Record fixtures (`python scripts/record_fixtures.py mysource`) and add offline tests.

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

```yaml
# sources.yaml
  - name: mysource
    enabled: true
    scope: jordan
    default_tags: [ai]
    options:
      url: https://example.com/events
```

To turn a source off, set `enabled: false`. `fetch --source mysource` still runs it.

---

## 📝 Manual Events (YAML)

The easiest way is the [Submit an event](https://github.com/ahmadodeh9000/HackWatch/issues/new?template=event.yml)
form (see [CONTRIBUTING.md](CONTRIBUTING.md)). You can also add events directly to `manual_events.yaml`:

```yaml
- title: My Local Hackathon
  url: https://example.com/hackathon
  dates: 2026-11-01 to 2026-11-03
  location: Amman, Jordan
  organizer: My Org
  prize: $5000
  type: hackathon        # hackathon | competition | conference | workshop | meetup | other
  mode: in-person        # in-person | online | hybrid (optional; default from location)
  tags: [ai, web]        # optional, from taxonomy.yaml
  scope: jordan          # optional: jordan (default) | worldwide
  registration_deadline: 2026-10-25   # optional
```

Dates must be ISO (`YYYY-MM-DD`). Use either `dates:` (one date, or `start to end`) or `start_date:` / `end_date:`.
When fetching, an invalid entry (bad date, unknown type/tag/mode, missing title or URL,
duplicate URL) is skipped with an error naming the entry; the other entries still import.
To check the file strictly, run:

```bash
python3 -m hackwatch.cli validate   # exits 1 if any entry is invalid
```

Then run **Fetch** (option 2) to import them into the database.

---

## 📦 Dependencies

| Package | Purpose |
|---------|---------|
| `requests` | HTTP requests for scrapers |
| `beautifulsoup4` | HTML parsing |
| `pyyaml` | YAML file handling |
| `typer` | CLI framework |
| `rich` | Beautiful terminal output |

---

## 📄 License

MIT — do whatever you want with it. Happy hacking! 🚀
