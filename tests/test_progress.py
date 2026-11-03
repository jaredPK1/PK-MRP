"""Today's win tile: only buys with a new PO in MAX are credited."""

from pkmrp.snapshot import progress


def buy(part, sos, value):
    return {"part": part, "sales_orders": sos, "order_value": value}


def test_only_a_new_po_counts_and_orders_count_once():
    previous = {
        "today": "2026-11-02",
        "buys": [buy("A", ["S1"], 100), buy("B", ["S1"], 100), buy("C", ["S2"], 50), buy("D", ["S3"], 9)],
        "so_values": {"S1": 100.0, "S2": 50.0, "S3": 9.0},
    }
    latest = {
        "today": "2026-11-03",
        "buys": [buy("D", ["S3"], 9), buy("E", ["S4"], 1)],
        "recent_po_parts": {
            "A": [["P1", "2026-11-02", 5.0]],
            "B": [["P2", "2026-11-03", 5.0]],
            "C": [["P0", "2026-10-01", 5.0]],  # old PO: C left because the plan changed
        },
    }
    p = progress(latest, previous)
    assert p["cleared"] == 2
    assert p["cleared_value"] == 100.0  # S1 once, not per buy
    assert p["moved"] == 1
    assert p["new"] == 1
