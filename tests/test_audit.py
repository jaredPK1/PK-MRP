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
