"""ledger/outcomes.py: what people did, matched from MAX's PO history."""

import json
from datetime import date, datetime

import pandas as pd

from pkmrp.ledger.outcomes import match

TODAY = date(2026, 11, 20)


def lines(*rows):
    cols = [
        "po",
        "line",
        "delivery",
        "part",
        "status",
        "created",
        "cur_due",
        "qty_current",
        "qty_received",
        "last_receipt",
    ]
    return pd.DataFrame(rows, columns=cols)


def rec(rec_id, kind, part, ref=None, qty=10.0, place_by=None, made="2026-10-28", detail=""):
    return {
        "rec_id": rec_id,
        "kind": kind,
        "part": part,
        "ref": ref,
        "qty": qty,
        "place_by": pd.Timestamp(place_by) if place_by else None,
        "created_at": datetime.fromisoformat(made + "T06:00:00"),
        "why_json": json.dumps({"detail": detail}),
    }


T = pd.Timestamp


def test_buy_matches_the_first_later_po_once():
    po = lines(
        ("70111001", "01", "01", "LENS", "3", T("2026-10-27"), T("2027-01-10"), 10, 0, None),
        ("70111100", "01", "01", "LENS", "3", T("2026-11-03"), T("2027-02-10"), 25, 0, None),
        ("70111200", "01", "01", "LENS", "3", T("2026-11-10"), T("2027-02-10"), 25, 0, None),
    )
    out = match(
        [
            rec(1, "buy", "LENS", place_by="2026-10-30"),
            rec(2, "buy", "LENS", place_by="2026-11-06", made="2026-10-29"),
        ],
        po,
        set(),
        TODAY,
    )
    placed = {o["rec_id"]: o["ref"] for o in out if o["what"] == "po_placed"}
    # the 10-27 PO is a day before rec 1: within grace, so it counts for rec 1
    assert placed == {1: "PO 70111001/01/01", 2: "PO 70111100/01/01"}
    first = next(o for o in out if o["rec_id"] == 1)
    assert json.loads(first["detail"])["workdays_after_place_by"] == -3


def test_expedite_push_cancel_and_receipt():
    po = lines(
        (
            "70110162",
            "01",
            "01",
            "LENS",
            "3",
            T("2026-05-01"),
            T("2026-11-10"),
            15,
            15,
            T("2026-11-12"),
        ),
        ("70111239", "01", "01", "SW", "3", T("2026-09-01"), T("2027-03-01"), 10, 0, None),
        ("70111269", "01", "01", "FPGA", "5", T("2026-10-26"), T("2026-11-10"), 10, 0, None),
    )
    recs = [
        rec(1, "expedite", "LENS", "PO 70110162/01/01", detail="due 2026-11-24, 15 needed"),
        rec(
            2,
            "push_out",
            "SW",
            "PO 70111239/01/01",
            detail="due 2026-12-10, first needed 2027-08-24",
        ),
        rec(3, "cancel", "FPGA", "PO 70111269/01/01", qty=10, detail="due 2026-11-10; no demand"),
    ]
    got = sorted((o["rec_id"], o["what"]) for o in match(recs, po, set(), TODAY))
    assert got == [(1, "po_expedited"), (1, "received"), (2, "po_pushed"), (3, "po_cancelled")]


def test_nothing_twice():
    po = lines(("70110162", "01", "01", "LENS", "3", T("2026-05-01"), T("2026-11-10"), 15, 0, None))
    r = [rec(1, "expedite", "LENS", "PO 70110162/01/01", detail="due 2026-11-24")]
    seen = set()
    assert len(match(r, po, seen, TODAY)) == 1
    assert match(r, po, seen, TODAY) == []
