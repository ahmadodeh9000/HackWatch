# Event sources

Status of every source HackWatch uses or has tried. Numbers come from a live
run on **2026-10-26** (`python scripts/record_fixtures.py`); the responses from
that run are saved in `tests/fixtures/` so the tests run offline.

"Raw" is what the scraper returned. "Kept" is what passed `filters.is_relevant`
(the gate in `db.upsert_event`). The site additionally hides events whose end
date is in the past.

## Active scrapers

Eventbrite and GDG rows were updated after Phase 1 (same day); the rest are the Phase 0 baseline.

| Source | Method | Requests | Raw | Kept | Status | Notes |
|---|---|---|---|---|---|---|
| Devpost | JSON API `devpost.com/api/hackathons` | 2 | 18 | 18 | ✅ Works | Only first 2 pages (9/page) of 175 total. All 18 were online. All had already started; they show because submissions end in the future. |
| Eventbrite | HTML search pages, JSON-LD `ItemList` | 8 | 11 | 5 | ✅ Works | **Jordan only**: 8 tech terms on `/d/jordan/<term>/`. Eventbrite returns the same ~10 Jordan events for every term. Online searches were dropped (see below). |
| GDG (gdg.community.dev) | JSON API, 8 Jordan chapter IDs + 1 detail call per upcoming event | 12 | 4 | 4 | ✅ Works | Was 0 kept before the Phase 1 filter fix. Only 3 of 8 chapters had anything upcoming. |
| JOSA (josa.ngo/events) | HTML, `div.preview` cards | 1 | 5 | 5 | ✅ Works | Page lists recent events; all 5 were already past on the run date, so the site shows none. Year is guessed (current year first). |
| Manual (`manual_events.yaml`) | Local YAML | 0 | 1 | 1 | ✅ Works | Only the example entry. Dates aren't validated. |

### Sample kept titles

- **Devpost:** Nebius x NVIDIA Global AI Hackathon · PayPal AI Hackathon · OpenCV AI Competition 2026
- **Eventbrite:** AI & Digital Transformation Conference 2026 · Cybersecurity & Data Protection Forum 2027 · Pocket Gamer Connects Jordan 2026
- **JOSA:** Hacktoberfest 2026 Amman · JOSA Workshop | Introduction to PCB Design · JOSA Treasure Hunt v2.0
- **Manual:** Amman AI Hackathon (Example)

### Sample dropped titles (and why)

In the Phase 0 baseline, all drops came from one rule: for `gdg` and
`eventbrite`, `is_relevant` required a hackathon-style keyword (`HACK_RE`).
Phase 1 replaced it with a tech-keyword check (`filters.is_tech_related`) for
non-tech-only sources. These were dropped at baseline:

- **GDG:** DevFest Amman 2026 · 🚀 Flutter Bootcamp: Learn App Development (×2, PSUT) · Mastering Research Papers (Zarqa)
- **Eventbrite, in Jordan:** AI & Digital Transformation Conference 2026 · Cybersecurity & Data Protection Forum 2027 · Pocket Gamer Connects Jordan 2026
- **Eventbrite, online:** Huawei Ireland Tech Arena 2026 · Find a Cofounder…
- **Correctly dropped, but by luck:** Costume Party 2026 (Amman) · "eyad alabade" (a 2014 junk listing) · IE University sales meetings

After Phase 1, Eventbrite still drops Costume Party, Entrepreneurship & Startup Growth Summit, Aqaba Blue and the IE one-to-one meeting. One known false positive is kept: "IE Masterclass: Globalization trends… AI opportunities".

### Data-quality issues seen in this run

- (Online searches only, now removed) Eventbrite marked some in-person events as online (e.g. "NASA Space Apps Challenge 2026 Boston", "…Singapore"), because the organiser set `OnlineEventAttendanceMode`. We trust the source.
- Eventbrite returns events years in the past ("eyad alabade", 2014-05-12); nothing filters past events before storing.
- GDG returns the same "Flutter Bootcamp" twice (two dated sessions with different URLs).
- No scraper sets an event type, so every scraped event (conferences and workshops too) would get the default `hackathon`.

### Why Eventbrite online searches were dropped

With 8 tech terms searched online, Eventbrite added 145 worldwide "online"
events, mostly generic webinars ("Remote Tech Sales Refresh", "UK Tech Nation
Visa Office Hour", "AI Governance for Leaders"). They buried the Jordan events
and were hard to filter by keyword. Worldwide online events now come only from
purpose-built feeds (Devpost, and later CTFtime and Codeforces).

## Tried and failed

| Source | What happened (checked 2026-10-26) | Verdict |
|---|---|---|
| Orange Jordan | `orange.jo/en/pages/events` returns **404**. No public events feed found. | Skip |
| ZINC (Zain Innovation Campus) | `zinc.jo` is a client-side React app: the HTML is an empty `<div id="root">`. Events would need a headless browser or an undocumented API. | Skip for now |
| PSUT | `psut.edu.jo/en/events` loads (200) but the HTML has only navigation; the event list is rendered client-side. PSUT events still arrive through the GDG on Campus PSUT chapter. | Skip; covered partly via GDG |
| University of Jordan | Every page returns a WAF block page ("Request Rejected") to non-browser clients. | Skip (blocks bots) |
| Telegram channels | Public web previews (`t.me/s/…`) exist, but scraping Telegram is out of scope by project rule. | Not allowed |

Instagram and Facebook are also out of scope by project rule.

## Not built yet

These were described as existing in earlier notes, but **do not exist** in the code:

- ~~`sources.yaml`~~: added in Phase 3. Each source's scope, defaults and options now live there.
- An IEEE vTools scraper.
- Event type inference. The `type` field itself only exists as uncommitted
  work in progress (as of 2026-10-26); it is set by hand in YAML and defaults to `hackathon`.
