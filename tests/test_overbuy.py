"""core/overbuy.py, and the Overbuys and Training pages render."""

from datetime import date

import pandas as pd

from pkmrp.core.netting import Demand, Exception_, Part, Peg
from pkmrp.core.overbuy import overbuys

TODAY = date(2026, 10, 28)


def test_po_problems_valued_by_buyer_new_flagged_committed_left_out():
    exc = [
        Exception_("SCREW", "cancel_candidate", ref="PO 70111001/01/01", qty=100),
        Exception_("LENS", "excess_on_po", ref="PO 70110001/01/01", qty=4),
        Exception_("FPGA", "cancel_candidate", ref="PO 70111155/01/01", qty=203),  # committed
        Exception_("SCREW", "unknown_part"),
    ]
    pos = pd.DataFrame(
        {
            "po": ["70111001", "70110001"],
            "line": ["01", "01"],
            "delivery": ["01", "01"],
            "buyer": ["AS", "LB"],
            "created": [pd.Timestamp("2026-10-20"), pd.Timestamp("2026-03-01")],
            "cur_due": [pd.Timestamp("2026-12-01"), pd.Timestamp("2026-11-15")],
        }
    )
    parts = {
        "SCREW": Part("SCREW", "B", unit_cost=0.5),
        "LENS": Part("LENS", "B", unit_cost=900),
        "FPGA": Part("FPGA", "B", unit_cost=179),
    }
    seg = [{"part": "FPGA", "segment": "committed"}]
    demands = {"LENS": [Demand("LENS", date(2026, 12, 1), 6, (Peg("so", "SO 1/01", "S"),), "so")]}
    out = overbuys(
        exc, pos, demands, {"LENS": 10, "SCREW": 0, "FPGA": 75}, parts, seg, {"LENS": "IDEX"}, TODAY
    )
    assert [r["part"] for r in out["po"]] == ["LENS", "SCREW"]  # by value, FPGA left out
    assert out["totals"]["not_needed"] == 50 and out["totals"]["more_than_needed"] == 3600
    assert out["totals"]["new"] == 50 and out["po"][1]["new"] and not out["po"][0]["new"]
    assert out["stock"][0]["part"] == "LENS" and out["stock"][0]["extra"] == 4
    assert {b["buyer"] for b in out["by_buyer"]} == {"AS", "LB"}


def _ob():
    po = [
        {"part": "SCREW", "ref": "PO 1/01/01", "kind": "cancel_candidate", "qty": 100, "value": 50.0,
         "buyer": "AS", "new": True},
        {"part": "LENS", "ref": "PO 2/01/01", "kind": "excess_on_po", "qty": 4, "value": 3600.0,
         "buyer": "LB", "new": False},
    ]
    stock = [{"part": "LENS", "extra": 4, "value": 3600.0, "idle": False}]
    totals = {"not_needed": 50.0, "more_than_needed": 3600.0, "early": 0, "new": 50.0,
              "new_lines": 1, "stock_extra": 3600.0, "stock_idle": 0}
    by_buyer = [{"buyer": "LB", "po_value": 3600.0, "po_lines": 1, "new_value": 0},
                {"buyer": "AS", "po_value": 50.0, "po_lines": 1, "new_value": 50.0}]
    return {"po": po, "stock": stock, "totals": totals, "by_buyer": by_buyer}


def test_cleared_rows_leave_the_list_and_the_totals_until_they_grow():
    from pkmrp.core.overbuy import apply_cleared

    cleared = {"PO|SCREW|PO 1/01/01": {"reason": "spares", "qty": 100},
               "STOCK|LENS": {"reason": "offsite", "qty": 3}}  # stock grew 3 -> 4
    out = apply_cleared(_ob(), cleared)
    assert [r["part"] for r in out["po"]] == ["LENS"]
    assert out["totals"]["not_needed"] == 0 and out["totals"]["new"] == 0
    assert out["totals"]["new_lines"] == 0 and out["totals"]["cleared"] == 50.0
    assert [b["buyer"] for b in out["by_buyer"]] == ["LB"]
    assert out["stock"][0]["was_cleared"]["reason"] == "offsite"  # back: it grew
    assert out["totals"]["stock_extra"] == 3600.0
    assert out["cleared_po"][0]["cleared"]["reason"] == "spares" and not out["cleared_stock"]
