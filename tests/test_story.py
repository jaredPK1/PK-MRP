"""core/story.py: the why story a buyer reads."""

from datetime import date

from pkmrp.core.calendar import plus_workdays
from pkmrp.core.netting import Demand, Peg
from pkmrp.core.story import build_story

TODAY = date(2026, 10, 28)
DESC = {"CLAMP": "SPLIT HUB CLAMP", "WHEEL": "APERTURE WHEEL ASSY", "SYS": "2304 MFD UNIT"}


def d(when, qty, so, line="05"):
    return Demand(
        "CLAMP",
        when,
        qty,
        (Peg("so", f"SO {so}/{line}", "SYS", ("SYS", "WHEEL", "CLAMP")),),
        "planned_make",
    )


def test_runs_out_action_and_who_is_waiting():
    demands = [
        d(date(2026, 11, 2), 15, "1"),
        d(date(2026, 12, 9), 4, "2"),
        d(date(2027, 3, 1), 6, "2", "20"),
    ]
    meta = {
        "1": {"customer": "ACME", "value": 5e5, "lines": {"05": date(2026, 12, 1)}},
        "2": {"customer": "ZED", "value": 2e6, "lines": {"05": date(2027, 1, 15)}},
    }
    s = build_story(
        "CLAMP",
        demands,
        [(date(2027, 1, 20), 3, "PO 7")],
        16,
        6,
        40,
        "PURLT_01",
        "REXNORD",
        TODAY,
        lambda p: DESC.get(p, ""),
        meta,
    )
    assert s["runs_out"] == date(2026, 12, 9) and s["covered_until"] == date(2026, 11, 2)
    assert s["total_need"] == 25 and s["on_order"] == 3
    assert s["arrives_if_ordered_today"] == plus_workdays(TODAY, 40)
    assert s["goes_into"] == [{"part": "WHEEL", "description": "APERTURE WHEEL ASSY", "units": 25}]
    w = {r["ref"]: r for r in s["waiting"]}
    assert w["SO 2"]["units"] == 10 and w["SO 2"]["customer"] == "ZED"
    # SO 1 (15 on 11-02) is covered by the 16 on hand: it doesn't slip.
    # SO 2's 12-09 need (4) is 3 short before a buy placed today lands.
    assert w["SO 1"]["ships"] == date(2026, 12, 1) and not w["SO 1"]["slips"]
    assert w["SO 1"]["covered"] and w["SO 2"]["slips"]
    assert w["SO 1"]["short_from"] is None and w["SO 2"]["short_from"] == date(2026, 12, 9)
    # short: 3 on 12-09, then the 1-20 PO (3) covers half of the 3-01 need (6)
    assert s["orders_slipping"] == 1 and s["short_total"] == 6
    bal = [m["balance"] for m in s["months"]]
    assert bal == [16 - 15, 1 - 4, -3 + 3, 0 - 6] and s["months"][0]["month"] == date(2026, 11, 1)


def test_nothing_short_means_no_run_out():
    s = build_story(
        "CLAMP",
        [d(date(2026, 12, 1), 2, "1")],
        [],
        5,
        0,
        10,
        "PURLT_01",
        "",
        TODAY,
        lambda p: "",
        {},
    )
    assert s["runs_out"] is None and s["orders_slipping"] == 0
