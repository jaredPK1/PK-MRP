"""The "why this buy?" story for one part, in the terms a buyer thinks in.

Not the engine's working (that's the netting ledger) but its answers:

  * when we run out, and how many more are needed in all;
  * what to do -- order this many from this vendor, when it would land, and
    which orders need it sooner than that;
  * what it goes into -- the assemblies one level up, with descriptions;
  * who's waiting -- customer orders, units of this part, when the part is
    needed and when the order ships;
  * month by month -- need, arrivals, balance.

Pure: the caller hands in the part's demands, receipts and plan.
"""

from collections import defaultdict
from datetime import date

from .calendar import plus_workdays


def _month(d):
    return date(d.year, d.month, 1)


def build_story(
    part,
    demands,
    receipts,
    on_hand,
    buy_qty,
    lead_days,
    lead_source,
    vendor,
    today,
    describe,
    so_meta,
    later_buys=(),
):
    """A dict for the why panel.

    demands   [Demand] netted against the part (date, qty, source, pegs)
    receipts  [(date, qty, ref)] open POs / WOs for the part
    describe  part -> description
    so_meta   so number -> {'customer', 'value', 'lines': {line: ship date}}
    later_buys [(place_by, qty)] planned buys past this week's horizon
    """
    demands = sorted(demands, key=lambda d: d.date)
    receipts = sorted(receipts)
    total_need = sum(d.qty for d in demands)

    # running balance through every event: when do we first go short?
    events = [(d.date, -d.qty) for d in demands] + [(r[0], r[1]) for r in receipts]
    events.sort(key=lambda e: (e[0], e[1] < 0))  # arrivals before needs on the same day
    bal, runs_out, covered_until = float(on_hand), None, None
    for when, delta in events:
        bal += delta
        if runs_out is None and delta < 0:
            if bal < -1e-9:
                runs_out = when
            else:
                covered_until = when

    arrive = plus_workdays(today, lead_days) if lead_days else today

    # Which demands stock and open receipts don't cover: only those can slip.
    uncovered = {}
    supply = [[r[0], r[1]] for r in receipts]
    stock = float(on_hand)
    for i, d in enumerate(demands):
        need = d.qty
        take = min(stock, need)
        stock -= take
        need -= take
        for s_ in supply:
            if need <= 1e-9:
                break
            if s_[1] > 1e-9 and s_[0] <= d.date:
                take = min(s_[1], need)
                s_[1] -= take
                need -= take
        uncovered[i] = need
    # orders whose need for this part falls before a buy placed today lands
    late_orders = set()

    # who's waiting: one row per customer order (or open WO / vendor kit)
    waiting = {}
    goes_into = defaultdict(float)
    for i, d in enumerate(demands):
        for p in d.pegs[:1] or ():
            parent = p.path[-2] if len(p.path) >= 2 else None
            if parent:
                goes_into[parent] += d.qty
            if p.kind == "so":
                so, line = p.ref[3:].split("/", 1) if "/" in p.ref else (p.ref[3:], "")
                meta = so_meta.get(so, {})
                key = ("so", so)
                row = waiting.setdefault(
                    key,
                    {
                        "kind": "order",
                        "ref": f"SO {so}",
                        "customer": meta.get("customer", ""),
                        "units": 0.0,
                        "need_by": d.date,
                        "ships": None,
                        "value": meta.get("value", 0.0),
                        "system": p.root_part,
                        "system_description": describe(p.root_part),
                    },
                )
                ship = meta.get("lines", {}).get(line)
                if ship and (row["ships"] is None or ship < row["ships"]):
                    row["ships"] = ship
            else:
                key = (p.kind, p.ref)
                row = waiting.setdefault(
                    key,
                    {
                        "kind": {
                            "wo_req": "open work order",
                            "po_kit": "vendor kit",
                            "sub_req": "subcontract PO",
                        }.get(p.kind, p.kind),
                        "ref": p.ref,
                        "customer": "",
                        "units": 0.0,
                        "need_by": d.date,
                        "ships": None,
                        "value": 0.0,
                        "system": p.root_part,
                        "system_description": describe(p.root_part),
                    },
                )
            row["units"] += d.qty
            row["need_by"] = min(row["need_by"], d.date)
            row.setdefault("short", 0.0)
            row["short"] += uncovered[i]
            if uncovered[i] > 1e-9:
                # the date this order's own shortage starts, not its first need
                row["short_from"] = min(row.get("short_from") or d.date, d.date)
                if d.date < arrive:
                    late_orders.add(key)
                    row["slips"] = True

    order_rows = sorted(waiting.values(), key=lambda r: (r["need_by"], -r["value"]))
    for r in order_rows:
        r.setdefault("slips", False)
        r.setdefault("short_from", None)
        r["covered"] = r.get("short", 0.0) <= 1e-9

    # month by month (anything already past due lands in this month)
    first = _month(today)
    months = defaultdict(lambda: {"need": 0.0, "arriving": 0.0})
    for d in demands:
        months[max(_month(d.date), first)]["need"] += d.qty
    for when, qty, _ref in receipts:
        months[max(_month(when), first)]["arriving"] += qty
    bal = float(on_hand)
    month_rows = []
    for m in sorted(months):
        bal += months[m]["arriving"] - months[m]["need"]
        month_rows.append(
            {
                "month": m,
                "need": months[m]["need"],
                "arriving": months[m]["arriving"],
                "balance": round(bal, 3),
            }
        )

    overdue = sum(d.qty for d in demands if d.date < today)
    return {
        "part": part,
        "description": describe(part),
        "on_hand": on_hand,
        "on_order": sum(r[1] for r in receipts),
        "total_need": round(total_need, 3),
        "runs_out": runs_out,
        "covered_until": covered_until,
        "overdue_need": round(overdue, 3),
        "buy_qty": buy_qty,
        "vendor": vendor,
        "lead_days": lead_days,
        "lead_source": lead_source,
        "arrives_if_ordered_today": arrive,
        "orders_slipping": len(late_orders),
        "short_total": round(sum(uncovered.values()), 3),
        "later_qty": round(sum(q for _, q in later_buys), 3),
        "later_place_by": min((p for p, _ in later_buys), default=None),
        "goes_into": [
            {"part": p, "description": describe(p), "units": round(q, 3)}
            for p, q in sorted(goes_into.items(), key=lambda x: -x[1])
        ][:8],
        "waiting": order_rows[:25],
        "waiting_more": max(len(order_rows) - 25, 0),
        "months": month_rows[:18],
    }
