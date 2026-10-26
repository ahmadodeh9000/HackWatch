# 🔍 HackWatch

**Jordan-focused tech & engineering event aggregator for your terminal.**

HackWatch tracks tech and engineering events (hackathons, contests, conferences, workshops, meetups) with a focus on Jordan: online events worldwide are included, while in-person events are filtered strictly to Jordan. It scrapes upcoming events from multiple sources, stores them in a local SQLite database, and lets you browse everything through an interactive terminal dashboard.

![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue)
![License: MIT](https://img.shields.io/badge/license-MIT-green)

🌐 **Live site:** https://ahmadodeh9000.github.io/HackWatch/

---

## ✨ Features

- **Jordan-focused** — Online events worldwide are tracked; in-person events only in Jordan
- **Multi-source scraping** — Devpost, Eventbrite, Google Developer Groups, JOSA, and manual YAML entries
- **Interactive dashboard** — Rich terminal UI with color-coded sources, urgency indicators, and event details
- **Smart date handling** — Events sorted by date, past events hidden by default, countdown indicators
- **Local-first** — All data stored in a single `hackwatch.db` SQLite file
- **Manual events** — Add your own events via YAML or the interactive prompt
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

# Export upcoming events to JSON
python3 -m hackwatch.cli export --out events.json
```

---

## 🏷️ Event fields

| Field | Values | Notes |
|-------|--------|-------|
| `type` | `hackathon`, `competition`, `conference`, `workshop`, `meetup`, `other` | `contest` is accepted as `competition`. Unknown or missing → `other`. Devpost events default to `hackathon`. |
| `mode` | `in-person`, `online`, `hybrid` | Default comes from the location (`Online` → `online`). Hybrid events count as online for filtering. |
| `tags` | ids from [`taxonomy.yaml`](taxonomy.yaml), e.g. `ai`, `ctf`, `cp`, `robotics`, `sumo`, `ieee` | Aliases work (`cybersecurity` → `security`). Unknown tags are an error in `manual_events.yaml`. |
| `scope` | `jordan`, `worldwide` | Set per source (Devpost: worldwide; Eventbrite, GDG, JOSA, manual: jordan). Can be overridden per event. |

The JSON export still includes the old `is_online` flag (`true` for online and hybrid) so older versions of the site keep working.

---

## 📁 Project Structure

```
HackWatch/
├── hackwatch.py              ← Interactive dashboard entry point
├── requirements.txt          ← Python dependencies
├── manual_events.yaml        ← Manually added events (YAML)
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
    ├── db.py                 ← SQLite database layer
    └── scrapers/
        ├── __init__.py
        ├── base.py           ← BaseScraper (rate-limited HTTP)
        ├── devpost.py        ← Devpost API scraper
        ├── eventbrite.py     ← Eventbrite LD+JSON scraper
        ├── gdg.py            ← Google Developer Groups API
        ├── josa.py           ← JOSA events page scraper
        └── manual.py         ← YAML file reader
```

---

## 🔧 Adding a New Scraper

1. Create a new file in `hackwatch/scrapers/` (e.g. `mysource.py`)
2. Subclass `BaseScraper` and implement `fetch() -> List[Event]`
3. Register it in `hackwatch/scrapers/__init__.py`
4. Add it to `get_available_scrapers()` in both `cli.py` and `hackwatch.py`

```python
from hackwatch.scrapers.base import BaseScraper
from hackwatch.models import Event

class MySourceScraper(BaseScraper):
    name = "mysource"

    def fetch(self) -> list[Event]:
        # Your scraping logic here
        return [Event(title="...", url="...", source=self.name)]
```

---

## 📝 Manual Events (YAML)

Add events directly to `manual_events.yaml`:

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
An invalid entry stops the import with an error that names the entry and the field.

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
