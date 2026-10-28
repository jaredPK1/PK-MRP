"""Promise check: the earliest date material supports for a new order line.

Replaces dating an order from a quoted lead time with no material check.
Given a part, a quantity and the date asked for, it returns the earliest
feasible date and which part holds it there.

Firm supply only -- on hand, open POs, open WOs -- after everything already
booked has taken its share (the plan's ledger with planned orders left
out). For a part:

  * in stock now (and no booked order needs it): today;
  * otherwise the earlier of (a) the date firm supply covers it after every
    booked order takes its share, and (b) making or buying it fresh -- if
    made here with a BOM, the latest date its components can be ready plus
    its build time (MFGLT_01 working days), recursively; if bought, today
    plus its lead time.

Build capacity is not modelled yet: no capacity data exists. The answer says
so instead of guessing. Pure functions; the web page calls promise().
"""

from datetime import date

from .calendar import plus_workdays

FIRM_SUPPLY = {"on_hand", "po", "wo"}
DEMAND = {"so", "wo_req", "planned_make", "planned_kit", "po_kit", "sub_req"}


def timelines(ledger):
    """{part: (start_qty, [(date, delta)])} of firm supply and committed demand,
    from netting's per-part ledger. Planned orders are not supply."""
    out = {}
    for part, entries in ledger.items():
        start, events = 0.0, []
        for when, qty, kind, _ref in entries:
            if kind == "on_hand":
                start += qty
            elif kind in FIRM_SUPPLY or kind in DEMAND:
                events.append((when, qty))
        events.sort(key=lambda e: e[0] or date.min)
        out[part] = (start, events)
    return out


def earliest_cover(timeline, need, today):
    """The earliest date from which the firm balance never drops below `need`
    again -- so taking `need` then hurts no booked order. None if never."""
    start, events = timeline
    if need <= 0:
        return today
    balances = [(today, start)]
    bal = start
    for when, delta in events:
        bal += delta
        balances.append((max(when or today, today), bal))
    # suffix minimum: the lowest the balance gets from each point on
    suffix, low = [0.0] * len(balances), float("inf")
    for i in range(len(balances) - 1, -1, -1):
        low = min(low, balances[i][1])
        suffix[i] = low
    for i, (when, _bal) in enumerate(balances):
        if suffix[i] >= need - 1e-9:
            return when
    return None


def promise(part, qty, requested, children, lines, parts, lead_of, today, max_depth=12):
    """{'date', 'requested', 'days_late', 'binding', 'path', 'steps', 'capacity'}."""
    steps = []

    def ready(p, need, depth, path):
        """(date, binding path): the earlier of waiting for firm supply and
        making / buying it fresh. A part already short for booked orders
        only frees up at the end of the horizon -- a new buy is sooner."""
        info = parts.get(p)
        covered = earliest_cover(lines.get(p, (0.0, [])), need, today)
        if covered == today:  # on the shelf now: nothing to build or buy
            steps.append({"part": p, "qty": need, "date": today, "how": "in stock", "path": path})
            return today, path
        kids = children.get(p, [])
        if info and info.type == "A" and kids and depth < max_depth:
            worst, worst_path = today, path
            for comp, qpu in kids:
                d, cp = ready(comp, need * qpu, depth + 1, path + (comp,))
                if d > worst:
                    worst, worst_path = d, cp
            fresh = plus_workdays(worst, info.mfg_lt)
            fresh_how = f"build: parts by {worst}, then {info.mfg_lt:g} working days"
        elif info and info.type == "A":
            fresh, worst_path = plus_workdays(today, info.mfg_lt), path
            fresh_how = f"build, {info.mfg_lt:g} working days (no BOM to check)"
        else:
            lt = lead_of(p)
            fresh, worst_path = plus_workdays(today, lt), path
            fresh_how = f"new buy today, {lt:g} business days" if info else "unknown part"
        if covered is not None and covered <= fresh:
            steps.append(
                {
                    "part": p,
                    "qty": need,
                    "date": covered,
                    "how": "on order (after booked orders take theirs)",
                    "path": path,
                }
            )
            return covered, path
        steps.append({"part": p, "qty": need, "date": fresh, "how": fresh_how, "path": path})
        return fresh, worst_path

    when, path = ready(part, float(qty), 0, (part,))
    binding = path[-1]
    steps.sort(key=lambda s: s["date"], reverse=True)
    return {
        "part": part,
        "qty": qty,
        "requested": requested,
        "date": when,
        "days_late": max((when - requested).days, 0) if requested else 0,
        "binding": binding,
        "path": path,
        "steps": steps[:25],
        "capacity": "not modelled yet -- material only",
    }
