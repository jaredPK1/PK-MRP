"""What to buy today: planned buys grouped by part and ranked.

A part's "buy now" is every planned buy whose place-by date is on or before
the horizon (default: five working days out) -- late ones first in spirit,
but ranked by what they unblock:

  1. booked orders waiting on it, in dollars -- whole sales orders, because
     82% of backlog lines carry no price of their own (a configured system's
     price sits on its 86/87/88 header line, not the 01- build line);
  2. how late the place-by date already is;
  3. spend, smallest first (cheap blockers are quick wins).

A buy that only restores MAX safety stock (no booked order behind it) goes
after all of those: the top of the list stays "orders slip without these".
Except on a part noted critical (single source, hard to replace): running
out would stop every booked order that uses it, so its safety-stock buy
goes to the top of the list (Jared, 2026-11-02: "work the top ten" must
cover them), biggest protected order first (`protects_*`; shown, never
counted as orders waiting -- none is short yet).

Pure: plain data in, plain dicts out, deterministic order.
"""

from collections import defaultdict

from .calendar import plus_workdays


def _so_of(ref):
    """'SO 20047846/03' -> '20047846'; anything else -> None."""
    if ref.startswith("SO "):
        return ref[3:].split("/")[0]
    return None


def sort_key(b):
    """Critical parts below safety stock first, then order-driven buys by the
    orders they unblock, then safety-stock top-ups. Also used by the web
    layer to re-rank when a critical note is added between plans."""
    if b.get("critical") and b.get("ss_qty"):
        tier = 0
    else:
        tier = 2 if b.get("ss_only") else 1
    return (tier, -max(b.get("order_value") or 0, b.get("protects_top") or 0),
            -(b.get("days_late") or 0), b.get("spend") or 0, b["part"])


def buy_list(
    planned,
    parts,
    lead_stats,
    so_values,
    so_customers,
    today,
    horizon_workdays=5,
    vendor_name=None,
    exclude=frozenset(),
    critical=frozenset(),
    demands=None,
):
    """[{part, ...}] for every part with a buy to place by the horizon, ranked."""
    horizon = plus_workdays(today, horizon_workdays)
    groups = defaultdict(list)
    for o in planned:
        if o.kind == "buy" and o.place_by <= horizon and o.part not in exclude:
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
        ss_qty = sum(o.qty for o in orders if o.reason == "safety_stock")
        protects = {}  # every safety-stock buy: a critical note can come later
        if ss_qty:
            for d in (demands or {}).get(part, []):
                for p in d.pegs:
                    so = _so_of(p.ref)
                    if so:
                        protects[so] = so_values.get(so, 0.0)
        out.append(
            {
                "part": part,
                "description": info.description if info else "",
                "buyer": info.buyer if info else "",
                "qty": qty,
                "unit_cost": unit_cost,
                "spend": round(qty * unit_cost, 2),
                "pack_qty": info.pack_qty if info else 0.0,
                "pack_uom": info.pack_uom if info else "",
                # only when the buy is whole packs (a keyed multiple can disagree)
                "packs": (
                    round(qty / info.pack_qty)
                    if info
                    and info.pack_qty
                    and abs(qty / info.pack_qty - round(qty / info.pack_qty)) < 1e-6
                    else None
                ),
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
                "wo_only": not orders_hit and ss_qty < qty - 1e-9,  # needed only by open WOs / kits
                "safety_stock": float(info.safety_stock or 0.0) if info else 0.0,
                "ss_qty": ss_qty,  # of qty, what restores safety stock
                "ss_only": ss_qty >= qty - 1e-9,  # no booked order behind it
                "critical": part in critical,
                "protects_orders": len(protects),
                "protects_value": round(sum(protects.values()), 2),
                "protects_top": round(max(protects.values(), default=0.0), 2),
            }
        )
    out.sort(key=sort_key)
    for i, b in enumerate(out, 1):
        b["rank"] = i
    return out
