"""Shelf parts: cheap things a catalog distributor ships in days.

A $0.12 McMaster screw doesn't belong in the top 10 as "19 weeks late" --
the 40-day lead is MAX's number; McMaster's real one, over 1,114 PO lines
since 2025, is about 4 calendar days. So a bought part is `shelf` when

  * its vendor is a catalog distributor (settings.shelf_vendors, matched on
    the name), and
  * it costs no more than settings.shelf_max_unit_cost each.

Shelf parts plan on the vendor's own measured delivery time (median of its
fully received lines, every part), are left out of the ranked buys and the
Overbuys page, and appear instead as one consolidated order per vendor,
with the vendor's own part numbers for a quick-order paste.

Bulk parts (TYPE_01 'Y', floor stock in MAX) are never planned at all.
"""

import math
from collections import defaultdict
from statistics import median

from .calendar import as_date, workdays_between


def is_shelf_vendor(name, settings):
    up = (name or "").upper().replace("-", "").replace(" ", "")
    return any(k.replace("-", "").replace(" ", "") in up for k in settings.shelf_vendors)


def vendor_speed(po_history, vendor_name_by_id, min_lines=10):
    """{vendor name: median working days, PO created -> last receipt} over
    fully received lines, for vendors with enough of them."""
    days = defaultdict(list)
    for r in po_history.itertuples(index=False):
        created, last = as_date(r.created), as_date(r.last_receipt)
        cur = float(r.qty_current or 0)
        if not created or not last or last < created or cur <= 0:
            continue
        if float(r.qty_received or 0) < 0.95 * cur:
            continue
        days[vendor_name_by_id.get(r.vendor_id, r.vendor_id)].append(
            workdays_between(created, last)
        )
    return {v: median(d) for v, d in days.items() if len(d) >= min_lines}


def shelf_parts(parts, vendor_of_part, settings):
    """{part: vendor name} for every bought part that is shelf stock."""
    out = {}
    for p, info in parts.items():
        if info.type not in settings.buy_types:
            continue
        vendor = vendor_of_part.get(p, "")
        if (
            vendor
            and is_shelf_vendor(vendor, settings)
            and float(info.unit_cost or 0) <= settings.shelf_max_unit_cost
        ):
            out[p] = vendor
    return out


def shelf_orders(planned, shelf, parts, vendor_part, speed, today, horizon):
    """One consolidated order per vendor: what to put in the cart this week."""
    by_vendor = defaultdict(list)
    for o in planned:
        if o.kind == "buy" and o.part in shelf and o.place_by <= horizon:
            by_vendor[shelf[o.part]].append(o)
    out = []
    for vendor, orders in by_vendor.items():
        items = defaultdict(lambda: {"qty": 0.0, "need_by": None})
        for o in orders:
            it = items[o.part]
            it["qty"] += o.qty
            it["need_by"] = min(filter(None, (it["need_by"], o.need_by)))
        rows = []
        for p, it in sorted(items.items(), key=lambda kv: kv[1]["need_by"]):
            info = parts.get(p)
            cost = float(info.unit_cost or 0) if info else 0.0
            qty = max(1, math.ceil(it["qty"] - 1e-9))  # catalogs sell whole units
            rows.append(
                {
                    "part": p,
                    "description": info.description if info else "",
                    "vendor_part": vendor_part.get(p, ""),
                    "qty": qty,
                    "spend": round(qty * cost, 2),
                    "need_by": it["need_by"],
                }
            )
        out.append(
            {
                "vendor": vendor,
                "lines": len(rows),
                "spend": round(sum(r["spend"] for r in rows), 2),
                "days": speed.get(vendor),
                "items": rows,
                "with_vendor_part": sum(1 for r in rows if r["vendor_part"]),
            }
        )
    out.sort(key=lambda v: -v["lines"])
    return out
