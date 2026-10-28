# Contributing to HackWatch

Thanks for helping Jordan's tech community find events! There are three ways to help.

## 1. Submit an event (no code needed)

Open the **[Submit an event](https://github.com/ahmadodeh9000/HackWatch/issues/new?template=event.yml)**
form. It's bilingual (English / العربية) and asks for:

- title, link, start date (and end date if it's more than one day), written as `YYYY-MM-DD`
- format: in-person, online or hybrid, plus the city and venue for in-person/hybrid events
- organizer, event type, optional tags (from [`taxonomy.yaml`](taxonomy.yaml)) and a short description

What happens next:

1. A maintainer reviews the issue and adds the `approved` label.
2. A bot checks the submission with `hackwatch validate`. If something is wrong (a date like
   `5/12/2026`, an unknown tag, a duplicate link), it comments on the issue and removes the label.
   Edit the issue and a maintainer re-approves it.
3. If it's valid, the bot opens a pull request adding the event to
   [`manual_events.yaml`](manual_events.yaml), with `Closes #<issue>`.
4. Once merged, the event appears on the site and in the calendar feed after the next update.

You can also edit `manual_events.yaml` directly in a pull request; the PR check runs
`hackwatch validate` and the tests. An entry looks like this:

```yaml
- title: Amman AI Hackathon
  url: https://example.com/amman-ai-hackathon
  dates: 2026-11-15 to 2026-11-17      # or a single date; always YYYY-MM-DD
  location: King Hussein Business Park, Amman
  organizer: My Club
  type: hackathon                      # hackathon | competition | conference | workshop | meetup | other
  mode: in-person                      # in-person | online | hybrid (default: from location)
  tags: [ai]                           # optional, ids from taxonomy.yaml
  prize: 500 JOD                       # optional
  start_time: "09:00"                  # optional, Amman time, 24 h
  end_time: "17:00"                    # optional
  registration_deadline: 2026-11-10    # optional, must be on or before the last day
  cost: free                           # optional: free | paid
  certificate: true                    # optional: true | false
  open_to: students                    # optional: anyone | students | members
  description: Optional, a few sentences.
```

### No GitHub account? The Google Form

For people without a GitHub account there's also a Google Form. Its responses are imported
with `hackwatch import-form`, which runs the same checks as `hackwatch validate`, skips links
that are already in `manual_events.yaml`, and reports invalid rows instead of importing them.

**Maintainer: how to set up the form.** The importer matches each column by the part of the
question title before ` / `, so the titles must start exactly like this (the Arabic part can
be changed). Mark the first three and Format, Organizer and Event type as required.

| # | Question title | Type | Settings |
|---|---|---|---|
| 1 | `Event title / اسم الفعالية` | Short answer | |
| 2 | `Event link / رابط الفعالية` | Short answer | Response validation → Text → URL |
| 3 | `Start date / تاريخ البدء` | Short answer | Response validation → Regular expression → Matches `^\d{4}-\d{2}-\d{2}$`, error text "Use YYYY-MM-DD, e.g. 2026-11-15". (Not the Date question type: its CSV format depends on the sheet's locale.) |
| 4 | `End date / تاريخ الانتهاء` | Short answer | Same regex; optional |
| 5 | `Start time / وقت البدء` | Time (or short answer `18:00`) | Optional; Amman time |
| 6 | `End time / وقت الانتهاء` | Time | Optional |
| 7 | `Registration deadline / آخر موعد للتسجيل` | Short answer | Same date regex; optional |
| 8 | `Format / طريقة الحضور` | Multiple choice | Options exactly: `In-person / حضوري`, `Online / عن بعد`, `Hybrid / مدمج` |
| 9 | `City and venue / المدينة والمكان` | Short answer | Optional (required for in-person/hybrid; the importer checks) |
| 10 | `Organizer / الجهة المنظمة` | Short answer | |
| 11 | `Event type / نوع الفعالية` | Multiple choice | Options exactly: `Hackathon / هاكاثون`, `Competition / مسابقة`, `Conference / مؤتمر`, `Workshop / ورشة عمل`, `Meetup / لقاء`, `Other / أخرى` |
| 12 | `Tags / الوسوم` | Checkboxes | Options (labels from `taxonomy.yaml`): AI & ML, Web, Mobile, Cloud & DevOps, Security, CTF, Competitive programming, Data, Robotics, Robot sumo, Line follower, Drones, Embedded & electronics, IoT, Game dev, AR / VR, Blockchain, Open source, Design & UX, Startups, IEEE, GDG, JOSA |
| 13 | `Description / الوصف` | Paragraph | Optional |
| 13a | `Cost / التكلفة` | Multiple choice | Optional; options `Free / مجاني`, `Paid / مدفوع`, `Not sure / غير متأكد` |
| 13b | `Certificate / شهادة` | Multiple choice | Optional; `Yes / نعم`, `No / لا`, `Not sure / غير متأكد` |
| 13c | `Open to / الفعالية مفتوحة لـ` | Multiple choice | Optional; `Anyone / الجميع`, `Students / الطلاب`, `Members / الأعضاء`, `Not sure / غير متأكد` |
| 14 | `Your email (optional) / بريدك الإلكتروني (اختياري)` | Short answer | Optional; never copied into the YAML |

Don't turn on "Collect email addresses" unless you want to; the importer ignores any
column it doesn't recognise.

**Importing responses:** in the form, *Responses → Download responses (.csv)*, then:

```bash
python -m hackwatch.cli import-form responses.csv --dry-run   # see what would happen
python -m hackwatch.cli import-form responses.csv             # append valid, new rows
git diff manual_events.yaml                                   # review: the form is open to anyone
```

Re-importing the same CSV later is safe: rows already imported are skipped as duplicates.

Then paste the form's public link into `GOOGLE_FORM_URL` at the top of the script in
[`docs/index.html`](docs/index.html); the "Google Form" option appears on the site once it's set.

### Already posted it on Instagram?

Send the post's link to the maintainer (the site shows a "Send us the Instagram post" option
once `INSTAGRAM_POST_URL` is set in `docs/index.html`). HackWatch never scrapes Instagram,
Facebook or Telegram; a maintainer adds the event by hand with `hackwatch add`. If the post links
to a registration page (Luma, Eventbrite, a Google Form…), `hackwatch add --from-url <link>`
pre-fills most fields from it.

### What gets hidden

Events whose title marks them as club life (inaugurations, officer kickoffs, opening
ceremonies, awareness days) are flagged `low_signal`: they stay in the data but the site hides
them unless "Show club life events" is on, and they're left out of the calendar feed and the
weekly digest. The keywords are under `low_signal:` in [`taxonomy.yaml`](taxonomy.yaml).

### Site settings (maintainers)

The top of the script in `docs/index.html` has the links that don't exist yet. Leave one
empty and its option isn't shown at all:

| Setting | What it is |
|---|---|
| `GOOGLE_FORM_URL` | The Google Form above |
| `INSTAGRAM_POST_URL` | Where to send an Instagram post, e.g. an `ig.me/m/<account>` DM link |
| `DIGEST_CHANNEL_URL` | WhatsApp/Telegram channel where the weekly digest is posted |
| `GOATCOUNTER_CODE` | GoatCounter site code (cookie-free page counts); empty = no analytics script |

## 2. Add a source (scraper)

Good sources are public, list events in Jordan (or online tech events), and can be read
without logging in. Instagram, Facebook and Telegram are out of scope. Check
[`SOURCES.md`](SOURCES.md) first: some sites have been tried and don't work.

1. Create `hackwatch/scrapers/<name>.py`: a `BaseScraper` subclass decorated with
   `@register("<name>")`, whose `fetch()` returns `Event`s. Use `self.get(...)`, which waits
   between requests, sends an honest User-Agent with the repo URL and times out after 60 s.
2. Import the module in `hackwatch/scrapers/__init__.py`.
3. Add it to [`sources.yaml`](sources.yaml) with its `scope` (`jordan` or `worldwide`),
   `default_type`, `default_tags` and `options` (passed to your constructor).
   Set `require_tech_keywords: true` if the source also lists non-tech events.
4. Record real responses and write offline tests:
   ```bash
   python scripts/record_fixtures.py <name>     # saves tests/fixtures/<name>/
   ```
   If responses are large, add a slimmer in `scripts/record_fixtures.py` (see `slim_vtools`).
   Freeze "today" in tests with the `frozen_today` fixture if your scraper compares dates.
5. Add a row to `SOURCES.md` with the numbers from your run.

Type and tags are guessed from the title, the source's own labels (`Event.source_labels`) and
the description using the rules in `taxonomy.yaml`. Set them explicitly only when the source
really knows them.

## 3. Run it locally and run the tests

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt

python -m pytest -q                      # offline, uses tests/fixtures/
python -m hackwatch.cli validate         # check manual_events.yaml
python -m hackwatch.cli fetch            # live fetch into hackwatch.db
python -m hackwatch.cli export --out docs/events.json --labels docs/labels.json --ics docs/events.ics \
  --digest docs/digest.txt --pages docs/e
python3 -m http.server 8000 --directory docs   # then open http://localhost:8000 (?lang=ar for Arabic)
```

CI runs Python 3.12; changes are also tested on 3.14 before pushing. If you have [uv](https://docs.astral.sh/uv/), you can test on it with
`uv run --python 3.12 --with-requirements requirements.txt --with pytest python -m pytest -q`.

Please keep pull requests small (one change each) and include tests.
