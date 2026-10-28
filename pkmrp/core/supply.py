"""Supply position: nettable on hand and open receipts (PO lines, open WOs)."""

from .calendar import as_date
from .netting import Receipt


def on_hand(stock):
    """{part: nettable on-hand qty}. Allocations are not subtracted: the WO
    requirements they reserve stock for are netted as demand instead."""
    return {
        r.part: float(r.on_hand or 0) for r in stock.itertuples(index=False) if (r.on_hand or 0) > 0
    }


def open_receipts(open_pos, open_wos, today):
    """[Receipt]. A receipt with no due date is assumed due today."""
    out = []
    for r in open_pos.itertuples(index=False):
        if (r.qty_due or 0) > 0:
            out.append(
                Receipt(
                    r.part,
                    as_date(r.cur_due) or today,
                    float(r.qty_due),
                    "po",
                    f"PO {r.po}/{r.line}/{r.delivery}",
                )
            )
    for r in open_wos.itertuples(index=False):
        if (r.qty_due or 0) > 0:
            out.append(
                Receipt(r.part, as_date(r.cur_due) or today, float(r.qty_due), "wo", f"WO {r.wo}")
            )
    return out
