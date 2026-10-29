"""One vendor, one PO: everything PK needs to buy from a vendor, together.

A buyer placing a buy for one part should see what else is coming due from
the same vendor and put it on the same PO -- one PO, one freight charge,
and the vendor sees the whole picture. This builds, per vendor, every part
with a planned buy inside a horizon (60 working days); the page picks the
window (2, 4, 8 or 12 weeks) and the buyer ticks what goes on the order.

  * a line is a part, with its planned buys (order by, need by, qty) so the
    window can include some and not others
  * committed parts are listed like any other -- their order-driven buys --
    with the blanket release as a note, never added on top (the release
    covers the same need)
  * shelf parts are included: a McMaster or Mouser order is a vendor order too
  * open POs with the vendor created recently are listed, since adding lines
    to one may beat a new PO
"""

import math
from collections import defaultdict
from datetime import date, timedelta

from .calendar import plus_workdays
from .rank import _so_of


def vendor_plan(
    planned,
    parts,
    vendor_name,
    vendor_part,
    so_values,
    so_customers,
    today,
    horizon_workdays=60,
):
    """{vendor: [line]} for every part with a planned buy by the horizon."""
    horizon = plus_workdays(today, horizon_workdays)
    by_part = defaultdict(list)
    for o in planned:
        if o.kind == "buy" and o.place_by <= horizon and vendor_name.get(o.part):
            by_part[o.part].append(o)
    out = defaultdict(list)
    for part, orders in by_part.items():
        info = parts.get(part)
        orders.sort(key=lambda o: o.place_by)
        rows = []
        for o in orders:
            sos = sorted({s for s in (_so_of(p.ref) for p in o.pegs) if s})
            rows.append([o.place_by, o.need_by, o.qty, sos])
        all_sos = sorted({s for r in rows for s in r[3]}, key=lambda s: -so_values.get(s, 0.0))
        out[vendor_name[part]].append(
            {
                "part": part,
                "description": info.description if info else "",
                "buyer": info.buyer if info else "",
                "vendor_part": vendor_part.get(part, ""),
                "unit_cost": float(info.unit_cost) if info else 0.0,
                "pack_qty": info.pack_qty if info else 0.0,
                "pack_uom": info.pack_uom if info else "",
                "orders": rows,
                "customers": sorted({so_customers.get(s, "") for s in all_sos} - {""}),
                "order_values": {s: round(so_values.get(s, 0.0), 2) for s in all_sos},
            }
        )
    return dict(out)


def recent_open_pos(open_pos, vendor_names_by_id, today, days=45):
    """{vendor: [{po, lines, created, next_due}]} for open POs created lately."""
    since = today - timedelta(days=days)
    acc = defaultdict(dict)
    for r in open_pos.itertuples(index=False):
        created = r.created.date() if hasattr(r.created, "date") else r.created
        if not r.vendor_id or created is None or created != created or created < since:
            continue
        v = vendor_names_by_id.get(r.vendor_id, r.vendor_id)
        due = r.cur_due.date() if hasattr(r.cur_due, "date") else r.cur_due
        po = acc[v].setdefault(r.po, {"po": r.po, "lines": 0, "created": created, "next_due": due})
        po["lines"] += 1
        if due and (po["next_due"] is None or due < po["next_due"]):
            po["next_due"] = due
    return {
        v: sorted(pos.values(), key=lambda p: p["created"], reverse=True) for v, pos in acc.items()
    }


def window(lines, today, horizon, soon):
    """The vendor's lines whose planned buys fall by `horizon` (a date): qty,
    packs, spend and how urgent, newest-need last. `soon` is the date a buy
    counts as due now (rank.buy_list's 5-working-day horizon)."""
    out = []
    for ln in lines:
        rows = [r for r in ln["orders"] if _d(r[0]) <= horizon]
        if not rows:
            continue
        qty = sum(r[2] for r in rows)
        place_by = min(_d(r[0]) for r in rows)
        need_by = min(_d(r[1]) for r in rows)
        pack = ln["pack_qty"] or 0
        sos = sorted({s for r in rows for s in r[3]}, key=lambda s: -ln["order_values"].get(s, 0))
        out.append(
            dict(
                ln,
                qty=qty,
                packs=math.ceil(qty / pack - 1e-9) if pack else None,
                spend=round(qty * ln["unit_cost"], 2),
                place_by=place_by,
                need_by=need_by,
                status="late" if place_by < today else "now" if place_by <= soon else "upcoming",
                sales_orders=sos,
                order_value=round(sum(ln["order_values"].get(s, 0) for s in sos), 2),
            )
        )
    rank = {"late": 0, "now": 1, "upcoming": 2}
    out.sort(key=lambda r: (rank[r["status"]], r["place_by"], r["part"]))
    return out


def _d(v):
    return v if isinstance(v, date) else date.fromisoformat(str(v)[:10])
