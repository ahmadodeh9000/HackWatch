"""Weekly series (GDG Flutter Bootcamp): one-day sessions, merged into one card."""
from datetime import date

from hackwatch.models import Event
from hackwatch.series import find_series, fix_session_ends, merge_series

BASE = "https://gdg.community.dev/events/details/psut-presents-flutter-bootcamp-"


def bootcamp(start, end):
    return Event(title="🚀 Flutter Bootcamp: Learn App Development", url=BASE + start, source="gdg",
                 organizer="GDG on Campus PSUT", start_date=start, end_date=end,
                 start_time="09:00", end_time="17:00", location="PSUT, Amman, Jordan", type="workshop")


# As listed on 2026-10-28: three Saturdays, each "ending" two weeks later.
LISTED = [bootcamp("2026-10-24", "2026-11-07"), bootcamp("2026-10-31", "2026-11-14"),
          bootcamp("2026-11-07", "2026-11-21")]
OTHER = Event(title="DevFest Amman 2026", url="https://x/devfest", source="gdg", organizer="GDG Amman",
              start_date="2026-11-28", type="conference")


def test_listings_a_week_apart_are_a_series():
    (series,) = find_series(LISTED + [OTHER])
    assert [e.start_date for e in series] == ["2026-10-24", "2026-10-31", "2026-11-07"]


def test_not_a_series_when_not_weekly_or_other_organiser():
    odd = [bootcamp("2026-10-24", "2026-10-24"), bootcamp("2026-10-27", "2026-10-27")]
    assert find_series(odd) == []
    other_org = Event(title="Flutter Bootcamp: Learn App Development", url="https://y", source="gdg",
                      organizer="GDG Irbid", start_date="2026-10-31")
    assert find_series([LISTED[0], other_org]) == []


def test_session_end_dates_are_the_session_day():
    fixed = fix_session_ends(LISTED + [OTHER])
    assert [(e.start_date, e.end_date) for e in fixed[:3]] == [
        ("2026-10-24", "2026-10-24"), ("2026-10-31", "2026-10-31"), ("2026-11-07", "2026-11-07")]
    assert fixed[3] is OTHER
    assert LISTED[0].end_date == "2026-11-07"  # originals untouched


def test_genuine_multi_day_events_in_a_series_keep_their_end():
    # Weekend hackathons every week, Fri-Sat: they don't run into the next one.
    weekly = [Event(title="Hack Night", url=f"https://h/{d}", source="gdg", start_date=d, end_date=e)
              for d, e in (("2026-11-06", "2026-11-07"), ("2026-11-13", "2026-11-14"))]
    assert [e.end_date for e in fix_session_ends(weekly)] == ["2026-11-07", "2026-11-14"]


def test_merged_card_counts_down_to_the_next_session():
    items = merge_series(fix_session_ends(LISTED + [OTHER]), today=date(2026, 10, 28))
    assert len(items) == 2
    series = items[0]
    assert series["event"].start_date == "2026-10-31"      # 24 Oct is over
    assert [s["date"] for s in series["sessions"]] == ["2026-10-31", "2026-11-07"]
    assert series["until"] == "2026-11-07"
    assert items[1]["sessions"] is None and items[1]["event"] is OTHER


def test_last_session_alone_is_a_normal_event():
    items = merge_series(fix_session_ends(LISTED), today=date(2026, 11, 2))
    assert len(items) == 1 and items[0]["sessions"] is None and items[0]["event"].start_date == "2026-11-07"
