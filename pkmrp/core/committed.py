"""Committed supply: a 12-month plan for the parts booked orders can't warn
about in time (core/segment.py's `committed`).

Replaces ad-hoc long-lead ordering one PO at a time and safety stock set by
email. Per committed part:

  1. requirement -- gross, by month, for 12 months: every open backlog line
     due in that window, walked down the BOM (and consigned kits) to the
     part, pulled earlier by the build time between it and the top-level
     part, grossed up by YIELD_01 when MAX has one. Pipeline (Book/Bill 2.0)
     is not in yet; `growth_bias` scales the whole requirement meanwhile.
  2. buffer -- service factor x monthly variation x sqrt(lead time in
     months); a flat-demand part with no variation gets 10% of a month.
  3. blanket -- 12-month requirement + buffer, less on hand and open POs,
     released monthly: each month's shortfall is ordered one P80 lead time
     ahead of when it's needed.
  4. forecast -- the monthly requirement tagged frozen (0-3 months),
     firm-ish (3-6) and indicative (6-12) for the supplier letter.

Pure: plain data in, plain dicts out.
"""

import math
from collections import defaultdict
from datetime import date

from .calendar import as_date, minus_workdays

HORIZON_MONTHS = 12
CAL_PER_BDAY = 7 / 5


def month_start(d):
    return date(d.year, d.month, 1)


def add_months(d, n):
    y, m = divmod(d.month - 1 + n, 12)
    return date(d.year + y, m + 1, 1)


def _explode(top, children, parts, cache):
    """{part: (qty per one top, build workdays between it and top)} below
    `top`, summed over every path, cycle-safe. Cached per top part."""
    if top in cache:
        return cache[top]
    out = defaultdict(lambda: [0.0, 0.0])
    stack = [(top, 1.0, 0.0, frozenset([top]))]
    while stack:
        part, mult, offset, seen = stack.pop()
        info = parts.get(part)
        build = float(info.mfg_lt) if info and info.type == "A" else 0.0
        for comp, qpu in children.get(part, ()):
            if comp in seen:
                continue
            q, off = mult * qpu, offset + build
            cell = out[comp]
            cell[0] += q
            cell[1] = max(cell[1], off)  # the longest path sets the timing
            stack.append((comp, q, off, seen | {comp}))
    cache[top] = {k: (v[0], v[1]) for k, v in out.items()}
    return cache[top]


def monthly_requirement(parts_wanted, so_lines, children, parts, settings, today):
    """{part: {month_start: qty}} for the next HORIZON_MONTHS, gross."""
    first = month_start(today)
    last = add_months(first, HORIZON_MONTHS)
    want = set(parts_wanted)
    cache, out = {}, defaultdict(lambda: defaultdict(float))
    for r in so_lines.itertuples(index=False):
        due = as_date(getattr(r, settings.demand_date, None)) or as_date(r.cur_due)
        if not due or due.year >= settings.unscheduled_from_year:
            continue
        qty = float(r.qty_due or 0)
        if qty <= 0:
            continue
        rows = dict(_explode(r.part, children, parts, cache))
        if r.part in want:
            rows[r.part] = (1.0, 0.0)
        for part, (per, offset) in rows.items():
            if part not in want:
                continue
            need = minus_workdays(due, offset)
            m = max(month_start(need), first)  # past-due is needed now
            if m < last:
                out[part][m] += qty * per
    return out


def plan_part(part, info, months, lead_bdays, on_hand, open_pos, settings, today):
    """The committed plan for one part. `months` {month_start: qty} gross;
    `open_pos` [(due date, qty, ref)]."""
    first = month_start(today)
    keys = [add_months(first, i) for i in range(HORIZON_MONTHS)]
    yld = float(info.yield_pct or 0)
    gross_up = 100.0 / yld if 0 < yld < 100 else 1.0
    req = [round(months.get(k, 0.0) * gross_up * settings.growth_bias, 3) for k in keys]
    total = sum(req)
    mean = total / HORIZON_MONTHS
    sd = math.sqrt(sum((q - mean) ** 2 for q in req) / HORIZON_MONTHS)
    lead_months = max(lead_bdays * CAL_PER_BDAY / 30.4, 0.25)
    buffer = settings.service_factor * (sd if sd > 0 else 0.1 * mean) * math.sqrt(lead_months)
    buffer = math.ceil(buffer) if mean > 0 else 0

    # Month by month: what's short after stock and open POs, ordered a lead
    # time ahead. The buffer is held from the first month on.
    supply_by_month = defaultdict(float)
    for due, qty, _ref in open_pos:
        supply_by_month[max(month_start(due), first)] += qty
    bal = float(on_hand)
    releases, schedule = [], []
    for i, k in enumerate(keys):
        bal += supply_by_month.get(k, 0.0) - req[i]
        short = max(buffer - bal, 0.0)
        if short > 1e-9:
            qty = math.ceil(short)
            bal += qty
            order_by = minus_workdays(k, lead_bdays)
            releases.append(
                {"month": k, "qty": qty, "order_by": order_by, "late": order_by < today}
            )
        schedule.append(
            {
                "month": k,
                "requirement": req[i],
                "arriving": supply_by_month.get(k, 0.0),
                "horizon": "frozen" if i < 3 else "firm" if i < 6 else "indicative",
            }
        )
    on_order = sum(q for _, q, _ in open_pos)
    return {
        "part": part,
        "description": info.description,
        "lead_bdays": lead_bdays,
        "requirement_12m": round(total, 2),
        "monthly_mean": round(mean, 2),
        "buffer": buffer,
        "on_hand": on_hand,
        "on_order": on_order,
        "blanket_qty": sum(r["qty"] for r in releases),
        "releases": releases,
        "schedule": schedule,
        "late_releases": sum(1 for r in releases if r["late"]),
        "yield_gross_up": round(gross_up, 3),
    }
