"""What to buy today: planned buys grouped by part and ranked.

A part's "buy now" is every planned buy whose place-by date is on or before
the horizon (default: five working days out) -- late ones first in spirit,
but ranked by what they unblock:

  1. booked orders waiting on it, in dollars -- whole sales orders, because
     82% of backlog lines carry no price of their own (a configured system's
     price sits on its 86/87/88 header line, not the 01- build line);
  2. how late the place-by date already is;
  3. spend, smallest first (cheap blockers are quick wins).

Pure: plain data in, plain dicts out, deterministic order.
"""

from collections import defaultdict

from .calendar import plus_workdays


def _so_of(ref):
    """'SO 20047846/03' -> '20047846'; anything else -> None."""
    if ref.startswith("SO "):
        return ref[3:].split("/")[0]
    return None


def buy_list(
    planned, parts, lead_stats, so_values, so_customers, today, horizon_workdays=5, vendor_name=None
):
    """[{part, ...}] for every part with a buy to place by the horizon, ranked."""
    horizon = plus_workdays(today, horizon_workdays)
    groups = defaultdict(list)
    for o in planned:
        if o.kind == "buy" and o.place_by <= horizon:
            groups[o.part].append(o)

    out = []
    for part, orders in groups.items():
        info = parts.get(part)
        lt = lead_stats.get(part) or {}
        qty = sum(o.qty for o in orders)
        place_by = min(o.place_by for o in orders)
        need_by = min(o.need_by for o in orders)
        orders_hit, roots, pegs = {}, set(), []
        for o in orders:
            for p in o.pegs:
                so = _so_of(p.ref)
                if so:
                    orders_hit[so] = so_values.get(so, 0.0)
                roots.add(p.root_part)
                pegs.append(p)
        unit_cost = float(info.unit_cost) if info else 0.0
        out.append(
            {
                "part": part,
                "description": info.description if info else "",
                "buyer": info.buyer if info else "",
                "qty": qty,
                "unit_cost": unit_cost,
                "spend": round(qty * unit_cost, 2),
                "place_by": place_by,
                "need_by": need_by,
                "days_late": max((today - place_by).days, 0),
                "lead_days": orders[0].lead_days,
                "lead_source": orders[0].lead_source,
                "vendor": (vendor_name or {}).get(part) or lt.get("vendor") or "",
                "orders": len(orders_hit),
                "order_value": round(sum(orders_hit.values()), 2),
                "customers": sorted({so_customers.get(so, "") for so in orders_hit} - {""}),
                "for_parts": sorted(roots),
                "sales_orders": sorted(orders_hit, key=lambda so: -orders_hit[so]),
                "planned_lines": len(orders),
                "wo_only": not orders_hit,  # needed only by open work orders / kits
            }
        )
    out.sort(key=lambda b: (-b["order_value"], -b["days_late"], b["spend"], b["part"]))
    for i, b in enumerate(out, 1):
        b["rank"] = i
    return out
