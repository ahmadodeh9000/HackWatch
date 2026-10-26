import json

from scripts.check_export import check, main


def test_zero_events_fails_even_without_previous():
    assert check(0, None, 0.5) == "export has 0 events"


def test_big_drop_fails():
    assert "less than 50%" in check(40, 100, 0.5)


def test_small_drop_and_growth_pass():
    assert check(60, 100, 0.5) is None
    assert check(300, 100, 0.5) is None


def test_unknown_previous_only_checks_zero():
    assert check(3, None, 0.5) is None


def test_main_exit_codes(tmp_path):
    out = tmp_path / "events.json"
    out.write_text(json.dumps([]))
    assert main([str(out)]) == 1
    out.write_text(json.dumps([{"title": "x"}]))
    assert main([str(out)]) == 0


def test_ratio_zero_disables_only_the_shrink_check():
    # CI's force=true input passes --min-ratio 0
    assert check(1, 100, 0) is None
    assert check(0, 100, 0) == "export has 0 events"
