"""core/weekly.py and the end-of-week email render."""

from datetime import date

from pkmrp.core import weekly

TODAY = date(2026, 10, 30)  # a Friday


def test_trend_compares_last_week_end_with_now_and_marks_good_moves():
    trend = {
        "2026-10-23": {"buy_now": 130, "late": 100, "order_value_waiting": 4.0e7},
        "2026-10-28": {"buy_now": 125, "late": 95, "order_value_waiting": 4.1e7},
        "2026-10-30": {"buy_now": 112, "late": 89, "order_value_waiting": 3.7e7},
    }
    rows, start, end = weekly.trend_rows(trend, TODAY)
    assert (start, end) == ("2026-10-23", "2026-10-30")
    buy = next(r for r in rows if r["key"] == "buy_now")
    assert buy["delta"] == -18 and buy["good"] is True
    assert weekly.trend_rows({}, TODAY) == ([], None, None)


def test_done_week_counts_this_week_only_and_by_person():
    log = [
        {"part": "A", "by": "aaron.chavarria@pk", "owner": "Aaron", "at": "2026-10-27T09:00:00", "check": "confirmed", "po": "1"},
        {"part": "B", "by": "rob.maier@pk", "owner": "", "at": "2026-10-29T09:00:00", "check": "no_po", "po": ""},
        {"part": "C", "by": "rob.maier@pk", "owner": "Rob", "at": "2026-10-29T10:00:00", "check": "undone", "po": ""},
        {"part": "D", "by": "x@pk", "owner": "Chad", "at": "2026-10-20T09:00:00", "check": "confirmed", "po": ""},
    ]
    d = weekly.done_week(log, TODAY)
    assert d["marked"] == 2 and d["confirmed"] == 1 and d["no_po"] == 1 and d["undone"] == 1
    assert dict(d["by_person"]) == {"Aaron": 1, "Rob": 1}
    assert [e["part"] for e in d["flagged"]] == ["B"]
