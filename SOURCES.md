# Event sources

Status of every source HackWatch uses or has tried. Numbers come from live runs
on **2026-10-26** (`python scripts/record_fixtures.py`). The responses are saved
(slimmed where noted) in `tests/fixtures/`, so the tests run offline.

"Raw" is what the scraper returned. "Kept" is what passed `filters.is_relevant`:
in-person events only in Jordan, online events from anywhere, and, for sources
with `require_tech_keywords`, a tech keyword. The site also hides past events.
Each source's settings live in [`sources.yaml`](sources.yaml).

## Active sources

| Source | Scope | Method | Requests | Raw | Kept | Notes |
|---|---|---|---|---|---|---|
| Devpost | worldwide | JSON API `devpost.com/api/hackathons` | 2 | 18 | 18 | First 2 pages (9/page) of ~175. All online. Types limited to hackathon/competition. |
| Eventbrite | jordan | HTML search pages, JSON-LD `ItemList` | 8 | 11 | 5 | ⚠️ **Blocked in CI** (see below); works from a home connection. 8 tech terms on `/d/jordan/<term>/`; Eventbrite returns the same ~10 Jordan events for any term. Needs a tech keyword. |
| GDG | jordan | JSON API, 8 Jordan chapters + 1 detail call per upcoming event | 12 | 4 | 4 | Only 3 of 8 chapters had upcoming events. GDG's own event tags and `audience_type` feed type/tag/mode inference. |
| JOSA | jordan | HTML `div.preview` cards on josa.ngo/events | 1 | 5 | 5 | Lists recent events; all 5 were past on the run date. Year is inferred (nearest to today). |
| IEEE (vTools) | jordan | Public vTools Events API v8, filtered client-side to section R80079 | 10 | 14 | 14 | See [IEEE vTools](#ieee-vtools) below; same-branch same-day posts are merged (14 → 11). |
| CTFtime | worldwide | Public API `ctftime.org/api/v1/events/`, next 60 days | 1 | 36 | 27 | The 9 dropped are on-site CTFs abroad (Italy, India, Canada, Riyadh...). Tags fixed to ctf + security. The free-text prize field is reduced to an amount ("$900", "€1,500+") or left empty; the full text goes into the description. |
| Codeforces | worldwide | API `contest.list`, next 30 days | 1 | 6 | 6 | Div. 1/2/3 and Educational rounds only (configurable). Fixture keeps upcoming + 5 finished of ~2000 contests. |
| Manual | jordan | `manual_events.yaml` | 0 | 1 | 1 | Community/club submissions. Invalid entries are skipped with an error; `hackwatch.cli validate` is strict. |

Live export on 2026-10-26 after Phases 2–3: 28 events (before IEEE/CTFtime/Codeforces).

### IEEE vTools

- **Public API, no auth:** `https://events.vtools.ieee.org/RST/events/api/public/v8/events/list`
  ([docs](https://events.vtools.ieee.org/api/doc/events)). JSON:API style; supports `span`
  (e.g. `now~now+60`), `limit`, `page`, `sort`, `category_id`, `tags`, `location_type`.
- **No public section filter.** The `spoid` parameter only works with a *named custom feed*,
  and custom feeds (per section/region/society) are "requested by contacting staff".
- **So we filter on our side.** Every event has `primary-host.section_spoids` (and co-hosts).
  The IEEE **Jordan Section is `R80079`** (seen on events from Yarmouk, Hashemite, GJU, Mutah,
  BAU, Zarqa, Philadelphia, UJ Aqaba student branches).
- **Cost:** ~1000 events worldwide in 60 days = ~10 pages of 100 (~0.5 MB, ~4 s each,
  sometimes much slower; one slow page is retried). Pages of 1000 took over 2 minutes, so
  100 is the sweet spot. Once a day this is acceptable.
- **Better option for later:** ask IEEE staff for a Jordan Section custom feed; then a
  single request with the feed `uid` would replace the paging.

### In CI (GitHub Actions) vs. locally

The deploy job publishes a per-source fetch report as
[`status.json`](https://ahmadodeh9000.github.io/HackWatch/status.json) (also in the job summary).

- **Eventbrite blocks GitHub's runners.** Run on 2026-10-26 21:56 UTC: all 8 requests got
  **HTTP 405 "Not Allowed"** with a page mentioning a captcha, in 0.15 s each. From a home
  connection the same URLs return 200. This is Eventbrite's bot protection refusing
  datacenter traffic, so HackWatch doesn't try to get around it. Options: (1) accept it and
  ask Jordan organisers who use Eventbrite to submit via the issue form; (2) disable the
  source (`enabled: false`) to stop sending 8 refused requests a day. The official Eventbrite
  API isn't an alternative: it needs a private token and its public event search was removed
  in 2020, so it only lists events of organisations you own.
  The per-source deploy guard can't help here: it keeps a source's events from the previous
  deploy, and no deploy has had Eventbrite events since moving to CI.
- **IEEE vTools works in CI** (10 × HTTP 200, 28 s in that run). An earlier run returned 0
  IEEE events; its log wasn't readable, so the cause is unknown (most likely a slow or
  failing API page, which then failed the whole source). The deploy guard now keeps the
  previous IEEE events, marked stale, if that happens again.

### Data-quality notes

- GDG lists multi-session events as separate events (e.g. two "Flutter Bootcamp" dates).
  Dedup never merges two listings from the same source, so both stay.
- Codeforces names many rounds identically ("Codeforces Round (Div. 2)"); dates and URLs differ.
- Eventbrite listings include non-tech events (parties, university sales meetings) and a
  2014 junk listing; the tech-keyword filter drops them. Known false positive kept:
  "IE Masterclass: Globalization trends… AI opportunities".
- CTF descriptions list challenge categories (web, crypto, hardware), so tag inference is
  off for CTFtime.
- IEEE city names are free text ("amman", "Az Zarqa"); all-lowercase ones are capitalised.
- IEEE: vTools has no field marking a post-event report, so titles with "Report"/"تقرير"
  are skipped, as are cancelled events. Several chapters of one student branch often post
  the same IEEE Day (e.g. Yarmouk's `STB25091`, `SBC25091A`, `SBA25091`); those merge when
  they're on the same day and their titles overlap.

### History

- Phase 0: the hackathon-only filter dropped every GDG event and Jordan tech conferences
  on Eventbrite. Replaced by the tech-keyword check (Phase 1), now a per-source setting.
- Phase 1: Eventbrite's online searches added ~145 worldwide webinars ("Remote Tech Sales
  Refresh", "UK Tech Nation Visa Office Hour") that buried Jordan events, so Eventbrite is
  Jordan-only. Worldwide online events come from purpose-built feeds instead.

## Tried and failed

| Source | What happened (checked 2026-10-26) | Verdict |
|---|---|---|
| Orange Jordan | `orange.jo/en/pages/events` returns **404**. No public events feed found. | Skip |
| ZINC (Zain Innovation Campus) | `zinc.jo` is a client-side React app: the HTML is an empty `<div id="root">`. Would need a headless browser or an undocumented API. | Skip for now |
| PSUT | `psut.edu.jo/en/events` loads but the event list is rendered client-side. PSUT events arrive via the GDG on Campus PSUT chapter and IEEE. | Skip; covered partly |
| University of Jordan | Every page returns a WAF block page ("Request Rejected") to non-browser clients. | Skip (blocks bots) |
| Telegram channels | Public previews (`t.me/s/…`) exist, but scraping Telegram is out of scope by project rule. | Not allowed |

Instagram and Facebook are also out of scope by project rule.

## Candidates (not built)

| Source | Finding (2026-10-26) | Verdict |
|---|---|---|
| Luma (lu.ma) | The public API (`api.lu.ma/public/v1/...`) answers "Please provide an API key"; keys belong to calendar owners. There's no public search. Each Luma calendar does publish an iCal feed. | Worth it **only** as a generic iCal source for specific Jordan community calendars, if clubs use Luma. |
| Meetup | The API is GraphQL behind OAuth (and Meetup Pro for most group data); the old REST API is gone. Few active Jordan tech groups. | Skip; groups can submit events via the issue form. |
| MLH | `mlh.com/seasons/2027/events` is server-rendered and allowed by robots.txt, but all 87 listed events are in-person, none in Jordan, so nothing would pass our filter. | Skip for now; revisit if MLH lists online events again. |
| ACM JCPC (Jordanian Collegiate Programming Contest) | One contest a year, announced by the hosting university; no feed. | Add by hand (manual YAML / issue form) each year. |

### Robotics competitions (checked 2026-10-27)

| Source | Finding | Verdict |
|---|---|---|
| WRO (World Robot Olympiad) Jordan | No Jordanian national WRO round or organiser found. The WRO member page renders its country list with JavaScript, so it can't be checked from a script. The nearest national round found was Palestine's, at Birzeit University (July 2026). | No source. |
| FIRST LEGO League Jordan | Run once a year (usually around March) by the Jubilee Institute / Jubilee Center for Excellence in Education (King Hussein Foundation), since 2005. Their site has news posts only; its calendar page is an empty month grid with no feed. FIRST's own event search loads results from an undocumented internal endpoint. | No clean source; add each year by hand or ask the Jubilee Center to use the issue form. |

Robotics events otherwise come from IEEE branches (RAS chapters) and community submissions;
`taxonomy.yaml` has English and Arabic keywords for robotics, sumo, line followers, drones
and embedded systems.

A generic **iCal source** (one URL per calendar in `sources.yaml`) would cover Luma
calendars, university calendars that publish `.ics`, and IEEE custom feeds, with one scraper.
