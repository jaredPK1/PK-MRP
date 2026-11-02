"""Is MAX's safety stock a good signal? Judge it before planning to it.

SAFSTK_01 is set by hand, once, and rarely revisited: 3,600+ bought parts
carry one. Some are deliberate and current (the 2920 single-source parts
Engineering flagged in October 2026); many are years old. Planning to every
one would fill the buy list with buffer for parts nobody uses.

Per bought part with safety stock, while it is netted (every booked need,
including demand exploded down from assemblies, is known by then):

  ignored  on hold, replaced by another part, or obsolete at its maker --
           buy what booked orders need, don't stock it;
           or no real use in 12 months and nothing booked -- a dormant part
           (used 12-24 months ago, or not in two years);
  capped   more than `max_months` of real use: held at that many months.
           Real use per month = the larger of the last 12 months' issues to
           work orders + shipments, and the booked rate (booked quantity
           spread from today to its last need, at least 3 months);
  trusted  everything else, planned as set.

Ignored and capped parts are a worklist for whoever keeps MAX's safety
stock (the Safety stock page and its CSV). Pure: plain data in, dicts out.
"""

import math

TRUSTED, CAPPED, IGNORED = "trusted", "capped", "ignored"


def booked_rate(demands, today, min_months=3.0):
    """Booked units per month across the part's demand."""
    total = sum(d.qty for d in demands if d.source != "safety_stock")
    if total <= 0:
        return 0.0
    last = max(d.date for d in demands if d.source != "safety_stock")
    months = max((last - today).days / 30.4, min_months)
    return total / months


def judge(ss, demands, usage, today, flag="", max_months=6.0):
    """{ss, use, verdict, why, used_12m, used_prior_12m, last_used, rate, months}.
    `usage` is (used 12 months, used the 12 before, last use) or None; `flag`
    is why the part shouldn't be stocked at all ('' if none)."""
    used, prior, last = usage or (0.0, 0.0, None)
    booked = sum(d.qty for d in demands if d.source != "safety_stock")
    rate = max(used / 12.0, booked_rate(demands, today))
    out = {
        "ss": ss,
        "used_12m": round(used, 2),
        "used_prior_12m": round(prior, 2),
        "last_used": last,
        "booked": round(booked, 2),
        "rate": round(rate, 2),
        "months": round(ss / rate, 1) if rate else None,
    }
    if flag:
        return dict(out, use=0.0, verdict=IGNORED, why=flag)
    if used <= 0 and booked <= 0:
        why = ("not used in 12 months and nothing booked" if prior > 0
               else "not used in two years and nothing booked")
        return dict(out, use=0.0, verdict=IGNORED, why=why)
    if ss > rate * max_months + 1e-9:
        use = float(math.ceil(rate * max_months))
        return dict(out, use=use, verdict=CAPPED,
                    why=f"{out['months']:g} months of use; holding {max_months:g} ({use:g})")
    return dict(out, use=ss, verdict=TRUSTED, why="")


def summary(judged, parts, buys, vendor_name=None):
    """The Safety stock page: counts by verdict, what the SS buys cost, and
    every part whose MAX number isn't planned as set (biggest $ first)."""
    vendor_name = vendor_name or {}
    ss_buys = [b for b in buys if b.get("ss_qty")]
    rows = []
    for part, j in judged.items():
        info = parts.get(part)
        cost = float(info.unit_cost or 0.0) if info else 0.0
        rows.append(dict(
            j, part=part, description=info.description if info else "",
            buyer=info.buyer if info else "", vendor=vendor_name.get(part, ""),
            unit_cost=round(cost, 4), value_set=round(j["ss"] * cost, 2),
            value_not_held=round((j["ss"] - j["use"]) * cost, 2),
        ))
    rows.sort(key=lambda r: (r["verdict"] == TRUSTED, -r["value_not_held"], r["part"]))
    count = {v: sum(1 for r in rows if r["verdict"] == v) for v in (TRUSTED, CAPPED, IGNORED)}
    return {
        "counts": count,
        "value_set": round(sum(r["value_set"] for r in rows), 2),
        "value_not_held": round(sum(r["value_not_held"] for r in rows), 2),
        "ss_buys": len(ss_buys),
        "ss_only_buys": sum(1 for b in ss_buys if b.get("ss_only")),
        "ss_spend": round(sum(b["ss_qty"] * (b.get("unit_cost") or 0) for b in ss_buys), 2),
        "rows": rows,
    }
