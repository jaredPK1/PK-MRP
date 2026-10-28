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
