"""core/shelf.py: catalog-distributor parts."""

from datetime import date

import pandas as pd

from pkmrp.core.netting import Part, Peg, PlannedOrder
from pkmrp.core.settings import PlanSettings
from pkmrp.core.shelf import is_shelf_vendor, shelf_orders, shelf_parts, vendor_speed

S = PlanSettings()
TODAY = date(2026, 10, 28)


def test_shelf_needs_a_catalog_vendor_and_a_low_price():
    assert is_shelf_vendor("McMASTER-CARR", S) and is_shelf_vendor("DIGIKEY CORPORATION", S)
    assert not is_shelf_vendor("REXNORD INDUSTRIES", S)
    parts = {
        "SCREW": Part("SCREW", "B", unit_cost=0.12),
        "SCOPE": Part("SCOPE", "B", unit_cost=900),
        "CLAMP": Part("CLAMP", "B", unit_cost=41),
        "SUB": Part("SUB", "A", unit_cost=1),
    }
    vend = {
        "SCREW": "McMASTER-CARR",
        "SCOPE": "MOUSER ELECTRONICS",
        "CLAMP": "REXNORD",
        "SUB": "McMASTER-CARR",
    }
    assert shelf_parts(parts, vend, S) == {"SCREW": "McMASTER-CARR"}


def test_vendor_speed_from_fully_received_lines():
    rows = [("V1", pd.Timestamp("2026-01-05"), pd.Timestamp("2026-01-08"), 10, 10)] * 12
    rows.append(("V1", pd.Timestamp("2026-01-05"), pd.Timestamp("2026-06-01"), 10, 2))  # partial
    h = pd.DataFrame(
        rows, columns=["vendor_id", "created", "last_receipt", "qty_current", "qty_received"]
    )
    assert vendor_speed(h, {"V1": "McMASTER-CARR"}) == {"McMASTER-CARR": 3}


def test_one_cart_per_vendor_with_their_part_numbers():
    pegs = (Peg("so", "SO 1/01", "SYS"),)
    planned = [
        PlannedOrder("SCREW", "buy", 123.2, date(2026, 11, 3), date(2026, 10, 29), 3, "x", pegs),
        PlannedOrder("SCREW", "buy", 6, date(2026, 11, 10), date(2026, 11, 5), 3, "x", pegs),
        PlannedOrder("NUT", "buy", 50, date(2027, 3, 1), date(2027, 2, 24), 3, "x", pegs),
    ]
    parts = {
        "SCREW": Part("SCREW", "B", description="SCREW", unit_cost=0.12),
        "NUT": Part("NUT", "B", unit_cost=0.1),
    }
    carts = shelf_orders(
        planned,
        {"SCREW": "McMASTER-CARR", "NUT": "McMASTER-CARR"},
        parts,
        {"SCREW": "91251A052"},
        {"McMASTER-CARR": 3},
        TODAY,
        date(2026, 11, 4),
    )
    (cart,) = carts
    assert cart["lines"] == 1 and cart["items"][0]["qty"] == 124  # the 11-05 one is next week
    assert cart["items"][0]["vendor_part"] == "91251A052" and cart["days"] == 3
