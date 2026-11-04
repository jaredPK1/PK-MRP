from datetime import date, datetime, timedelta

import pandas as pd

from pkmrp.core.audit import recent_po_lines, repeat_pos, run_audit

TODAY = date(2026, 10, 30)
NOW = datetime(2026, 10, 30, 10, 9)


def _pos(rows):
    return pd.DataFrame(
        [
            {"po": po, "part": part, "created": pd.Timestamp(c), "qty_due": q, "buyer": b}
            for po, part, c, q, b in rows
        ],
        columns=["po", "part", "created", "qty_due", "buyer"],
    )


ROB_AARON = _pos(
    [
        ("70111303", "35-0126-00G", TODAY - timedelta(days=1), 14.0, "RM"),
        ("70111321", "35-0126-00G", TODAY, 15.0, "AC"),
        ("70100000", "OTHER", TODAY - timedelta(days=20), 5.0, "RM"),
        ("70100001", "OTHER", TODAY - timedelta(days=2), 5.0, "RM"),
    ]
)


def test_repeat_po_two_buyers_one_day_apart():
    f = repeat_pos(recent_po_lines(ROB_AARON, TODAY), {})
    assert [x["part"] for x in f] == ["35-0126-00G"]
    assert f[0]["total"] == 29


def test_rebuy_jump_and_state():
    prev = {
        "buys": {
            "35-0126-00G": {"first_seen": "2026-10-30T07:09", "qty": 2, "need_by": "2026-12-04"}
        }
    }
    snap = {
        "buys": [
            {
                "part": "35-0126-00G",
                "qty": 15,
                "need_by": "2026-11-16",
                "days_late": 7,
                "sizing": {"policy": "economic"},
            }
        ]
    }
    audit, state = run_audit(snap, prev, ROB_AARON, TODAY, NOW)
    kinds = {f["check"] for f in audit["findings"]}
    assert {"rebuy", "jumped", "repeat_po"} <= kinds
    assert snap["buys"][0]["changed"]["kind"] == "earlier"
    assert state["buys"]["35-0126-00G"]["first_seen"] == "2026-10-30T07:09"
    assert audit["extra_pos_30d"] == 1


def test_flip_only_when_no_po_followed():
    prev = {
        "buys": {
            "A": {"first_seen": "2026-10-30T08:09", "qty": 4, "need_by": "2026-11-20"},
            "35-0126-00G": {"first_seen": "2026-10-30T08:09", "qty": 15, "need_by": "2026-11-16"},
        }
    }
    audit, state = run_audit({"buys": []}, prev, ROB_AARON, TODAY, NOW)
    flips = [f["part"] for f in audit["findings"] if f["check"] == "flip"]
    assert flips == ["A"]  # the cable went because Aaron ordered it
    assert len(state["flips"]) == 1


def test_sitting_and_trend():
    prev = {
        "buys": {"B": {"first_seen": "2026-10-25T08:00", "qty": 1, "need_by": "2026-11-01"}},
        "trend": [{"date": "2026-10-29", "pos_30d": 3, "extra_pos_30d": 0}],
    }
    snap = {"buys": [{"part": "B", "qty": 1, "need_by": "2026-11-01", "days_late": 12}]}
    audit, state = run_audit(snap, prev, _pos([]), TODAY, NOW)
    assert any(f["check"] == "sitting" for f in audit["findings"])
    assert [t["date"] for t in state["trend"]] == ["2026-10-29", "2026-10-30"]


def test_safety_stock_top_up_is_not_a_jump():
    empty = _pos([])
    # the day safety stock was switched on: 2 for orders became 2 + 10 safety stock
    prev = {"buys": {"37-0007-01G": {"first_seen": "2026-11-02T08:02", "qty": 2,
                                     "need_by": "2026-12-04"}}}
    snap = {"buys": [{"part": "37-0007-01G", "qty": 12, "ss_qty": 10, "need_by": "2026-12-04"}]}
    audit, state = run_audit(snap, prev, empty, TODAY, NOW)
    assert "changed" not in snap["buys"][0] and state["buys"]["37-0007-01G"]["ss_qty"] == 10
    # the part for orders really grew: flagged, saying how much is safety stock
    prev = {"buys": {"62-2567-01G": {"first_seen": "2026-11-02T08:02", "qty": 214,
                                     "need_by": "2026-11-23"}}}
    snap = {"buys": [{"part": "62-2567-01G", "qty": 954, "ss_qty": 250, "need_by": "2026-11-23"}]}
    run_audit(snap, prev, empty, TODAY, NOW)
    assert snap["buys"][0]["changed"]["text"] == (
        "For booked orders, went from 214 to 704 since the last plan (plus 250 safety stock)")


def test_rebuy_counts_only_booked_orders_short_of_the_po():
    pos = _pos([("70111350", "37-0105-00G", TODAY - timedelta(days=1), 9.0, "AC"),
                ("70111310", "37-0083-01G", TODAY - timedelta(days=1), 12.0, "AC"),
                ("70111315", "62-0145-01G", TODAY - timedelta(days=1), 5.0, "AC")])
    snap = {"buys": [
        # the PO covered the orders; all that's left is safety stock
        {"part": "37-0105-00G", "qty": 8, "min_qty": 8, "ss_qty": 8, "need_by": "2027-02-11"},
        # 6 short for orders, 5 safety stock on top
        {"part": "37-0083-01G", "qty": 11, "min_qty": 11, "ss_qty": 5, "need_by": "2027-03-30"},
        # safety stock 2, sized up to 26 weeks of cover: still not a short PO
        {"part": "62-0145-01G", "qty": 43, "min_qty": 2, "ss_qty": 2, "need_by": "2026-12-24"},
    ]}
    audit, _ = run_audit(snap, {}, pos, TODAY, NOW)
    by = {f["part"]: f for f in audit["findings"] if f["check"] in ("rebuy", "rebuy_ss")}
    assert by["37-0083-01G"]["check"] == "rebuy" and by["37-0083-01G"]["want"] == 6
    assert by["37-0083-01G"]["what"].endswith("booked orders need 6 more (plus 5 safety stock)")
    assert by["37-0105-00G"]["check"] == "rebuy_ss" and by["37-0105-00G"]["want"] == 8
    assert by["62-0145-01G"]["check"] == "rebuy_ss" and by["62-0145-01G"]["want"] == 2
    assert audit["counts"] == {"rebuy": 1, "rebuy_ss": 2}
