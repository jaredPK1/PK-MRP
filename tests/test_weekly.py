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


def test_priorities_order_new_first_and_skip_empty():
    snap = {
        "buys": [
            {"part": "LATE", "description": "x", "qty": 5, "vendor": "ACME", "days_late": 9,
             "orders": 2, "order_value": 900, "place_by": "2026-10-20"},
            {"part": "LATER", "place_by": "2026-12-20", "qty": 1},
        ],
        "headline": {"buy_now": 1},
        "audit": {"findings": [{"check": "repeat_po", "part": "R", "what": "2 POs in 2 days",
                                "pos": [{"po": "1"}, {"po": "2"}]}]},
    }
    eol_items = [
        {"part": "E1", "kind": "obsolete", "tier": "act", "booked": 5, "on_hand": 1, "on_order": 0,
         "ltb_qty": 20, "ltb_cost": 40.0, "signals": [{"detail": "digikey: Obsolete"}],
         "alternates": [{"mpn": "ALT-1", "maker": "ACME", "status": "unchecked"}]},
        {"part": "E2", "kind": "obsolete", "tier": "fyi", "booked": 0, "on_hand": 0, "on_order": 0,
         "ltb_qty": 0, "ltb_cost": 0, "signals": [], "alternates": []},
    ]
    alerts = [{"kind": "price_up", "vendor_id": "9", "vendor": "V", "part": "A", "impact": 10, "what": "w"},
              {"kind": "price_up", "vendor_id": "9", "vendor": "V", "part": "B", "impact": 99, "what": "w"}]
    seen = {"prices": ["price_up|9|B"], "buys": ["LATE"]}
    secs = weekly.priorities(snap, date(2026, 11, 2), eol_items, alerts, [], None, seen)
    assert [s["key"] for s in secs] == ["buys", "eol", "prices", "repeat"]
    buys, eol, prices = secs[0], secs[1], secs[2]
    assert [r["part"] for r in buys["items"]] == ["LATE"] and buys["total"] == 1 and buys["new"] == 0
    assert [r["part"] for r in eol["items"]] == ["E1"] and "ALT-1" in eol["items"][0]["extra"]
    assert [r["part"] for r in prices["items"]] == ["A", "B"] and prices["new"] == 1  # new first
    assert secs[3]["new"] == 0  # no repeat list last time: nothing marked


def test_title_names_the_biggest_sections():
    from pkmrp.cli import weekly_title

    wk = {"week_of": "2026-11-02", "new_total": 3, "sections": [
        {"total": 12, "title": "Buys to place", "label": "buys to place"},
        {"total": 5, "title": "Parts going obsolete", "label": "parts going obsolete"}]}
    assert weekly_title(wk) == "PK-MRP, week of Nov 2: 12 buys to place, 5 parts going obsolete (3 new)"
    assert weekly_title({"week_of": "2026-11-02", "sections": []}).endswith("nothing needs you")
