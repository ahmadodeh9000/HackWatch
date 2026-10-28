"""docs/digest.png: the weekly digest as an image."""
from datetime import date

import pytest

PIL = pytest.importorskip("PIL")
from PIL import Image  # noqa: E402

from hackwatch import cli  # noqa: E402
from hackwatch.digest import build_digest  # noqa: E402
from hackwatch.digestimage import HEIGHT, WIDTH, is_rtl, render  # noqa: E402
from hackwatch.models import Event  # noqa: E402

TODAY = date(2026, 11, 1)


def ev(title, start, **kw):
    kw.setdefault("scope", "jordan")
    return Event(title=title, url=f"https://example.com/{abs(hash(title))}", source="manual", start_date=start, **kw)


def test_renders_portrait_png_with_events_and_closing(tmp_path):
    events = [ev("IEEE Day UJ-Aq", "2026-11-03", start_time="11:00", type="meetup", location="Aqaba, Jordan"),
              ev("هاكاثون الذكاء الاصطناعي", "2026-11-02", type="hackathon", location="عمّان"),
              ev("🚀 Flutter Bootcamp", "2026-11-04", type="workshop"),
              ev("Robot Sumo Cup", "2026-11-20", registration_deadline="2026-11-05", type="competition")]
    digest = build_digest(events, today=TODAY)
    assert len(digest.this_week) == 3 and len(digest.closing) == 1
    path = tmp_path / "digest.png"
    warnings = render(digest, path)
    with Image.open(path) as img:
        assert img.size == (WIDTH, HEIGHT) == (1080, 1350)
        assert img.format == "PNG"
    assert all("raqm" in w for w in warnings)  # the only possible warning


def test_empty_week_still_renders(tmp_path):
    path = tmp_path / "empty.png"
    render(build_digest([], today=TODAY), path)
    assert Image.open(path).size == (1080, 1350)


def test_direction_from_first_letter():
    assert is_rtl("هاكاثون IEEE") and not is_rtl("IEEE هاكاثون") and not is_rtl("2026 ...")
    assert is_rtl("2026 هاكاثون")


def test_export_writes_digest_png(tmp_path):
    from typer.testing import CliRunner
    from hackwatch import db

    db_path = tmp_path / "t.db"
    conn = db.get_connection(db_path)
    db.init_db(conn)
    out = tmp_path / "docs"
    out.mkdir()
    result = CliRunner().invoke(cli.app, ["export", "--db", str(db_path), "--out", str(out / "events.json"),
                                          "--digest-png", str(out / "digest.png")])
    assert result.exit_code == 0, result.output
    assert Image.open(out / "digest.png").size == (1080, 1350)
