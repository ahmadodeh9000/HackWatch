# Learning the HackWatch code

A short guided tour, in the order data flows: a scraper fetches → filters decide what to keep →
the database stores and merges → the deploy workflow publishes. Read each stop with the file
open; links go to the exact lines. At the end are three small exercises.

Setup once:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
python -m pytest -q            # ~350 tests, offline, about 2 seconds
```

---

## Stop 1: an event's life starts in a scraper (the IEEE one)

File: [hackwatch/scrapers/vtools.py](hackwatch/scrapers/vtools.py), configured in
[sources.yaml](sources.yaml) under `name: ieee`.

- **Registration.** `@register("vtools")` puts the class in a registry by name.
  `sources.yaml` says `scraper: vtools` and passes `options:` (like `section_spoids: [R80079]`)
  straight to `__init__`. That's how one scraper class can serve several sources (the `bevy`
  scraper serves both GDG and Startup Grind).
- **Politeness lives in the base class.** `BaseScraper.get()` in
  [scrapers/base.py](hackwatch/scrapers/base.py) waits `delay_seconds` between requests,
  sends `User-Agent: HackWatch/... (+repo URL)`, times out after 60 s, retries a dropped
  connection once, and logs every request (that log becomes `status.json`). IEEE's robots.txt
  asks for `Crawl-delay: 60`, so `sources.yaml` sets `delay_seconds: 60`.
- **The problem it solves.** IEEE's public API can't filter by country, so
  [`fetch()`](hackwatch/scrapers/vtools.py:66) pages through every upcoming IEEE event in the
  world (`_page`, [line 51](hackwatch/scrapers/vtools.py:51)) and keeps only those whose host
  or co-host belongs to the Jordan Section (`_in_sections`,
  [line 58](hackwatch/scrapers/vtools.py:58)).
- **Cleaning.** Post-event reports are skipped by title (`REPORT_RE`), cancelled events too.
  City names are typed freely, so all-lowercase ones get capitalised. Dates and times are
  converted to Amman time with helpers in [timeutil.py](hackwatch/timeutil.py); note
  [`deadline_date`](hackwatch/timeutil.py:56): vTools stores "registration closes 20 Oct" as
  midnight of the 21st, so exactly-midnight means "the day before".
- **Output.** Every scraper returns a list of `Event` objects
  ([models.py](hackwatch/models.py)). That dataclass is the common language of the whole
  project.

Try it: `python -m pytest -q tests/test_vtools.py -v`. The tests replay real API answers saved
in `tests/fixtures/ieee/`, so they never touch the network.

## Stop 2: filters decide what's in scope

File: [hackwatch/filters.py](hackwatch/filters.py). Small, and the project's rules in code.

- [`is_relevant`](hackwatch/filters.py:48) is the gate. Read it top to bottom: manual events
  always pass; "TBD" titles and events more than a year away are dropped; **in-person events
  outside Jordan are dropped** (online ones from anywhere stay); and, only for sources that ask
  for it (`require_tech_keywords: true` in `sources.yaml`, e.g. Eventbrite), there must be a
  tech word.
- [`is_in_jordan`](hackwatch/filters.py:37): a detected country code wins; otherwise a regex of
  Jordanian cities on the location text (`JORDAN_RE`, [line 4](hackwatch/filters.py:4)).
  The comment explains why: "Jordan, MN, US" is not Jordan.
- [`is_tech_related`](hackwatch/filters.py:44): one big regex built from English patterns
  (`TECH_TERMS_EN`) and Arabic stems (`TECH_TERMS_AR`). The English ones are wrapped in `\b`
  word boundaries; the Arabic ones aren't, because Arabic attaches prefixes like ال and بال to
  words ("بالذكاء").

Note what is *not* here: type, tags and "club life" are decided in
[infer.py](hackwatch/infer.py) from rules in [taxonomy.yaml](taxonomy.yaml). Filters decide
whether an event is kept at all; inference labels the ones that are.

## Stop 3: the database keeps what each source said, then merges

File: [hackwatch/db.py](hackwatch/db.py). Two tables matter:

- **`observations`**: one row per (source, page URL), the event exactly as that source
  listed it, stored as JSON. See `_create_observations`.
- **`events`**: the merged result, rebuilt from observations every time.

The fetch loop in [cli.py](hackwatch/cli.py:98) calls, for each source that worked:

1. [`replace_source_events`](hackwatch/db.py:172): writes this run's observations for that
   source (only the ones `is_relevant` keeps) and deletes that source's observations that it
   no longer lists. That's how a cancelled event disappears. A source that *failed* is not
   called at all, so its old rows survive.
2. [`rebuild_events`](hackwatch/db.py:192) (once, after all sources): loads every
   observation, merges duplicates with [dedup.py](hackwatch/dedup.py) (same URL, or a similar
   title within a day from another source), and rewrites `events`. Each event's `id` is a hash
   of its normalised URL, so it's the same every day; the share pages `e/<id>.html` rely on it.

Why two tables? Merging is easy to redo but impossible to undo. Keeping each source's raw
listing means a fix to dedup or a source's removal just needs a rebuild, no re-fetch.

Look inside your own database: `sqlite3 hackwatch.db "select source, count(*) from observations group by source"`.

## Stop 4: the deploy workflow publishes it

File: [.github/workflows/update.yml](.github/workflows/update.yml). It runs daily at 03:00 UTC,
on every push to `main`, and by hand. Read the steps in order; each `name:` says what it does.

1. **Tests first.** If they fail, nothing is fetched or deployed.
2. **Fetch** (`|| true`: a broken source never stops the deploy) and write `status.json`.
3. **Health**: counts empty runs per source and opens a "Source down" issue after two.
4. **Carry-over**: a source that had events on the live site but returned nothing keeps them,
   marked stale, for up to 7 days ([carryover.py](hackwatch/carryover.py)). This is what keeps
   one bad night at IEEE from emptying the site.
5. **Export** everything the site reads: `events.json`, `labels.json`, `events.ics`,
   `digest.txt`, `digest.png`, `e/<id>.html`.
6. **Refuse** to deploy an export with 0 events or under half of what's live
   ([scripts/check_export.py](scripts/check_export.py)).
7. **Deploy** to Pages, then **check the live site** ([scripts/check_live.py](scripts/check_live.py)):
   a "successful" deploy once served an empty site, so the job now looks at what visitors get.

`concurrency: group: pages, cancel-in-progress: true` means a new push cancels a deploy that's
still running. `permissions:` lists only what the job needs (Pages, reading the repo, issues).

---

## Exercises

Do them on a branch; each should take under an hour. Run `python -m pytest -q` when done.

### 1. Teach the filter a new city (filters.py)

Events in **Salt** and **Mafraq** (السلط، المفرق) aren't recognised as Jordan when a source gives
only a city name. Add them to `JORDAN_RE`, and add a test to
[tests/test_filters.py](tests/test_filters.py) like `test_in_person_outside_jordan_dropped`
that builds `Event(title="Robotics Day", url="https://x", source="gdg", mode="in-person",
location="Salt")` and asserts `is_relevant` is `True`.
*Then think:* why does `"Jordan, MN, US"` still not pass? (Hint: `country`.)

### 2. Ask the database a question (db.py)

Write `count_by_source(conn) -> dict` in `db.py` returning `{"ieee": 11, "gdg": 5, ...}` from the
**events** table, counting an event once per source in its `sources` list (it's stored as JSON
text, so `json.loads` it). Test it in a temporary database: `init_db`, `upsert_event` two events
with the same URL from two sources, and check both sources count 1. Why is it one event and not
two? Find the line in `dedup.py` that decides.

### 3. Make IEEE look further ahead (sources.yaml + the test fixtures)

Change `days_ahead` for `ieee` in `sources.yaml` from 60 to 90. **Before running anything,
predict:** will `python -m pytest -q tests/test_vtools.py` still pass? Then run it.

It fails with `No recorded response for GET https://events.vtools.ieee.org/...span=now~now%2B90...`.
Open the `replay` fixture in [tests/conftest.py](tests/conftest.py) and find why: recorded
responses are looked up by the exact request URL, query string included, and a request that
isn't recorded fails instead of quietly going to the network. Answer in one sentence each:
(a) why is failing better than going to the network here? (b) what would you run to record new
fixtures (see `scripts/record_fixtures.py`), and roughly how long would it take with
`Crawl-delay: 60` and pages of 200? (c) why would 90 days make the real daily run slower?
Put the value back to 60 when you're done (or re-record and update the tests' expected counts).
