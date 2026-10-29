"""core/vendor_order.py and the vendor pages: one PO per vendor."""

import json
from datetime import date

import pandas as pd
from test_rank_web import client  # noqa: F401 -- the snapshot-backed app fixture

from pkmrp.core.calendar import plus_workdays
from pkmrp.core.netting import Part, Peg, PlannedOrder
from pkmrp.core.vendor_order import recent_open_pos, vendor_plan, window

TODAY = date(2026, 10, 29)  # a Thursday
PARTS = {
    "A": Part("A", "B", "BRACKET", unit_cost=10.0),
    "B": Part("B", "B", "PLATE", unit_cost=4.0),
    "C": Part("C", "B", "SCREW", unit_cost=0.1, pack_qty=100, pack_uom="PK"),
    "D": Part("D", "B", "LENS", unit_cost=50.0),
}
VENDOR = {"A": "XOMETRY", "B": "XOMETRY", "C": "XOMETRY", "D": "THORLABS"}


def order(part, qty, place_by, refs=("SO 20047846/01",)):
    pegs = tuple(Peg("so", r, "SYS", ("SYS", part)) for r in refs)
    return PlannedOrder(part, "buy", qty, place_by, place_by, 20, "x", pegs)


def plan():
    planned = [
        order("A", 2, date(2026, 10, 27)),  # late
        order("B", 5, date(2026, 11, 2)),  # due now (within 5 wd)
        order("C", 150, date(2026, 11, 20)),  # 3 weeks out
        order("C", 50, date(2026, 12, 30)),  # 9 weeks out
        order("D", 1, date(2026, 11, 2)),
        order("E", 1, date(2026, 11, 2)),  # no vendor: not on any order
    ]
    return vendor_plan(
        planned, PARTS, VENDOR, {"A": "XO-A"}, {"20047846": 900.0}, {"20047846": "Acme"}, TODAY
    )


def test_a_vendor_order_gathers_due_now_and_coming_up():
    p = json.loads(json.dumps(plan(), default=str))  # as the snapshot stores it
    assert sorted(p) == ["THORLABS", "XOMETRY"]
    soon = plus_workdays(TODAY, 5)
    two = window(p["XOMETRY"], TODAY, plus_workdays(TODAY, 10), soon)
    assert [(r["part"], r["status"]) for r in two] == [("A", "late"), ("B", "now")]
    four = window(p["XOMETRY"], TODAY, plus_workdays(TODAY, 20), soon)
    c = next(r for r in four if r["part"] == "C")
    assert c["status"] == "upcoming" and c["qty"] == 150 and c["packs"] == 2
    twelve = window(p["XOMETRY"], TODAY, plus_workdays(TODAY, 60), soon)
    c = next(r for r in twelve if r["part"] == "C")
    assert c["qty"] == 200 and c["spend"] == 20.0
    a = four[0]
    assert a["vendor_part"] == "XO-A" and a["customers"] == ["Acme"] and a["order_value"] == 900.0


def test_recent_open_pos_by_vendor_name():
    pos = pd.DataFrame(
        [
            ("70111262", "XO", pd.Timestamp("2026-10-20"), pd.Timestamp("2026-11-30")),
            ("70111262", "XO", pd.Timestamp("2026-10-20"), pd.Timestamp("2026-11-10")),
            ("70100001", "XO", pd.Timestamp("2025-01-02"), pd.Timestamp("2026-11-10")),
        ],
        columns=["po", "vendor_id", "created", "cur_due"],
    )
    out = recent_open_pos(pos, {"XO": "XOMETRY"}, TODAY)
    assert list(out) == ["XOMETRY"] and len(out["XOMETRY"]) == 1
    assert out["XOMETRY"][0]["lines"] == 2 and out["XOMETRY"][0]["next_due"] == date(2026, 11, 10)


def test_vendor_pages(client):  # noqa: F811
    from pkmrp import snapshot

    snap = snapshot.load_latest()
    snap["vendor_plan"] = json.loads(json.dumps(plan(), default=str))
    snap["today"] = TODAY.isoformat()
    snapshot.write(snap)
    page = client.get("/vendors").get_data(as_text=True)
    assert "Xometry" in page and "Thorlabs" in page
    page = client.get("/vendor?v=XOMETRY&weeks=4&part=B").get_data(as_text=True)
    assert 'data-part="A"' in page and 'data-part="C"' in page and 'class="focus"' in page
    assert "coming up" in page and "XO-A" in page
    assert client.get("/vendor?v=NOBODY").status_code == 404
