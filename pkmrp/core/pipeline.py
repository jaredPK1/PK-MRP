"""Book/Bill 2.0 pipeline as material demand, for committed parts only.

The design principle is that the backlog is the plan -- except for the few
committed parts, whose lead time outruns the backlog. For those, open
bookings not yet on an SO add probability-weighted demand in their billing
month, so a 12-month blanket covers deals likely to land.

  * weight   = win probability (as Book/Bill 2.0 weights its forecast);
               x go probability too when settings.pipeline_use_go is on
  * when     = the first of the booking's billing month; undated bookings
               are counted on a worklist, not guessed into a month
  * what     = the line item's product SKU, and each option's SKU x the line
               quantity. A SKU that is a MAX part number is used as is; one
               that isn't is looked up in `sku_map` (mrp_settings
               'pipeline_sku_map', confirmed on the Pipeline page), else it
               goes on the unmapped worklist -- never guessed. A map entry is
               a part number, {"part", "qty_per"}, or {"skip": true} for a
               SKU that is no material (a license, a service, a note).

Output rows look like open_so_lines rows (so, line, part, qty_due, cus_due,
cur_due, unit_price, customer), so committed.monthly_requirement can walk
them down the BOM exactly as it walks the backlog.
"""

from collections import defaultdict
from datetime import date

import pandas as pd


def resolve(entry):
    """A pipeline_sku_map entry -> (part, qty_per), "skip", or None."""
    if isinstance(entry, str):
        return (entry, 1.0) if entry.strip() else None
    if isinstance(entry, dict):
        if entry.get("skip"):
            return "skip"
        if entry.get("part"):
            return entry["part"], float(entry.get("qty_per") or 1.0)
    return None


def pipeline_demand(lines, known_parts, sku_map, settings):
    """(frame of demand rows, worklist dict)."""
    rows = []
    unmapped = defaultdict(lambda: {"qty": 0.0, "bookings": set(), "description": ""})
    skipped = defaultdict(float)
    undated = {}
    for r in lines.itertuples(index=False):
        sku = (r.sku or "").strip()
        qty = float(r.qty or 0)
        if not sku or qty <= 0:
            continue
        w = float(r.p_win or 0) / 100.0
        if settings.pipeline_use_go:
            w *= float(r.p_go or 0) / 100.0
        if w <= 0:
            continue
        if r.bill_year != r.bill_year or r.bill_month != r.bill_month or not r.bill_year:
            u = undated.setdefault(
                r.booking,
                {
                    "booking": r.booking,
                    "customer": r.customer,
                    "status": r.status,
                    "p_win": float(r.p_win or 0),
                    "skus": [],
                },
            )
            if sku not in u["skus"]:
                u["skus"].append(sku)
            continue
        found = (sku, 1.0) if sku in known_parts else resolve(sku_map.get(sku))
        if found == "skip":
            skipped[sku] += qty * w
            continue
        part, per = found or (None, 1.0)
        if not part:
            u = unmapped[sku]
            u["qty"] += qty * w
            u["bookings"].add(r.booking)
            u["description"] = u["description"] or (r.description or "")
            continue
        when = date(int(r.bill_year), int(r.bill_month), 1)
        rows.append(
            {
                "so": f"BK {r.booking}",
                "line": str(int(r.item_id)),
                "part": part,
                "qty_due": round(qty * per * w, 4),
                "cus_due": pd.Timestamp(when),
                "cur_due": pd.Timestamp(when),
                "unit_price": 0.0,
                "customer": r.customer,
                "source": "pipeline",
            }
        )
    frame = pd.DataFrame(
        rows,
        columns=[
            "so",
            "line",
            "part",
            "qty_due",
            "cus_due",
            "cur_due",
            "unit_price",
            "customer",
            "source",
        ],
    )
    work = {
        "unmapped": sorted(
            (
                {
                    "sku": k,
                    "weighted_qty": round(v["qty"], 2),
                    "bookings": len(v["bookings"]),
                    "description": v["description"],
                }
                for k, v in unmapped.items()
            ),
            key=lambda x: -x["weighted_qty"],
        ),
        "undated_bookings": len(undated),
        "undated": sorted(undated.values(), key=lambda u: (-u["p_win"], u["booking"])),
        "skipped": {k: round(v, 2) for k, v in skipped.items()},
        "bookings": len({r["so"] for r in rows}),
        "lines": len(rows),
    }
    return frame, work
