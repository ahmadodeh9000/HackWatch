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
  registration_deadline: 2026-11-10    # optional
  description: Optional, a few sentences.
```

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
python -m hackwatch.cli export --out docs/events.json --labels docs/labels.json --ics docs/events.ics
python3 -m http.server 8000 --directory docs   # then open http://localhost:8000
```

CI runs Python 3.12. If you have [uv](https://docs.astral.sh/uv/), you can test on it with
`uv run --python 3.12 --with-requirements requirements.txt --with pytest python -m pytest -q`.

Please keep pull requests small (one change each) and include tests.
