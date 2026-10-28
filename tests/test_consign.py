"""core/consign.py: the consigned-kit list is learned from what PK sent."""

from datetime import date

import pandas as pd

from pkmrp.core.consign import consigned_edges, open_kit_demand, subcontract_demand
from pkmrp.core.netting import Demand, Part, Peg, plan
from pkmrp.core.settings import PlanSettings

TODAY = date(2026, 10, 28)

BOM = pd.DataFrame(
    {
        "parent": ["BOARD", "BOARD", "BOARD", "CABLE"],
        "component": ["FPGA", "RES", "PCB", "WIRE"],
        "qty_per": [1.0, 40.0, 1.0, 2.0],
        "type_code": ["N", "E", "E", "N"],
    }
)


def test_only_components_pk_sent_for_that_parent_count():
    moves = pd.DataFrame(
        {
            "component": ["FPGA", "FPGA", "RES"],
            "po": ["70109903", "70109903", "70100000"],
            "moved": [pd.Timestamp("2026-06-11")] * 3,
        }
    )
    po_parts = pd.DataFrame({"po": ["70109903", "70100000"], "parent": ["BOARD", "OTHER"]})
    sub = pd.DataFrame({"parent": ["CABLE"], "part": ["WIRE"]})
    kids, ev = consigned_edges(moves, po_parts, sub, BOM)
    assert kids == {"BOARD": [("FPGA", 1.0)], "CABLE": [("WIRE", 2.0)]}
    assert ev[("BOARD", "FPGA")]["moves"] == 2 and ev[("CABLE", "WIRE")]["sub_reqs"] == 1
    # RES was sent, but for a PO of a different parent: not BOARD's kit.


def test_open_board_po_owes_its_kit_unless_it_is_a_subcontract_line():
    pos = pd.DataFrame(
        {
            "po": ["70111269", "70111270"],
            "line": ["01", "01"],
            "part": ["BOARD", "BOARD"],
            "qty_due": [10.0, 5.0],
            "cur_due": [pd.Timestamp("2026-12-11")] * 2,
        }
    )
    out = open_kit_demand(
        pos, {"BOARD": [("FPGA", 1.0)]}, {("70111270", "01")}, lambda p: 20, TODAY
    )
    (d,) = out
    assert (d.part, d.qty, d.source) == ("FPGA", 10.0, "po_kit")
    assert d.date < date(2026, 12, 11)


def test_subcontract_open_rows_are_demand():
    sub = pd.DataFrame(
        {
            "po": ["70110001"],
            "line": ["01"],
            "parent": ["CABLE"],
            "part": ["WIRE"],
            "qty_open": [4.0],
            "due": [pd.Timestamp("2026-11-30")],
            "status": ["3"],
        }
    )
    demands, lines = subcontract_demand(sub, TODAY)
    assert lines == {("70110001", "01")} and demands[0].qty == 4.0


def test_planned_board_buy_explodes_only_its_consigned_kit():
    parts = {
        "BOARD": Part("BOARD", "B", purchase_lt=30),
        "FPGA": Part("FPGA", "B", purchase_lt=200),
    }
    peg = (Peg("so", "SO 1/01", "BOARD", ("BOARD",)),)
    r = plan(
        parts,
        {"BOARD": [("FPGA", 1.0)]},
        [Demand("BOARD", date(2027, 3, 1), 4, peg, "so")],
        {},
        [],
        PlanSettings(),
        TODAY,
    )
    board = next(o for o in r.planned if o.part == "BOARD")
    fpga = next(o for o in r.planned if o.part == "FPGA")
    assert fpga.qty == 4 and fpga.need_by == board.place_by
    assert fpga.pegs[0].path == ("BOARD", "FPGA")
