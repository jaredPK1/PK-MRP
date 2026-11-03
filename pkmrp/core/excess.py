"""Excess stock: inventory beyond what the plan needs, for the reserve.

Replaces Tim (VP Finance) building the excess & obsolete reserve list from
MAX's MRP, which counts hand-keyed -FAMILY forecast entries as demand and has
no usable obsolete flag. Every stocked part PK makes or buys is measured
against what PK-MRP plans for it:

  * everyday parts -- every booked order and open work order netted against
    the part (made parts carry the demand their parents pass down after the
    parents' own stock), plus the safety stock PK-MRP holds;
  * long-lead (committed) parts -- bought a year ahead on purpose, so they
    are measured against their 12-month requirement plus buffer instead;
  * a long-lead part with no committed plan yet falls back to booked demand.

Valued per stocking unit (COST_01 / CSTCNV_01). Usage is issues and shipments
(Transaction_History I + S), so the reserve tiers can age the excess. Bulk
(type Y) is not planned and not here. Pure.
"""

from collections import defaultdict

LONG_LEAD = ("committed", "unproven_long")


def excess(demands, stock, parts, segments, committed_plans, usage, settings,
           safety_floor=None):
    """{'rows': [...] biggest first, 'totals': {...}}."""
    seg = {r["part"]: r["segment"] for r in segments}
    plans = {c["part"]: c for c in committed_plans}
    floor = safety_floor or {}
    kinds = {**{t: "made" for t in settings.make_types}, **{t: "bought" for t in settings.buy_types}}
    rows = []
    for p, on_hand in stock.items():
        info = parts.get(p)
        if not info or info.type not in kinds or on_hand <= 0:
            continue
        if any(p.startswith(x) for x in settings.doc_prefixes):
            continue
        cost = float(info.unit_cost or 0)
        if cost <= 0:
            continue
        booked = sum(d.qty for d in demands.get(p, ()))
        plan = plans.get(p)
        if plan is not None:
            basis = "12-month plan"
            needed = float(plan["requirement_12m"] or 0) + float(plan["buffer"] or 0)
        else:
            basis = "booked"
            needed = booked + floor.get(p, 0.0)
        extra = on_hand - needed
        if extra <= 1e-9:
            continue
        used_12m, used_prior, last_used = usage.get(p, (0.0, 0.0, None))
        rate = used_12m / 12.0
        rows.append(
            {
                "part": p,
                "description": info.description,
                "kind": kinds[info.type],
                "basis": basis,
                "long_lead": seg.get(p) in LONG_LEAD,
                "on_hand": round(on_hand, 3),
                "booked": round(booked, 3),
                "needed": round(needed, 3),
                "extra": round(extra, 3),
                "unit_cost": round(cost, 4),
                "value": round(extra * cost, 2),
                "on_hand_value": round(on_hand * cost, 2),
                "idle": needed <= 1e-9,
                "used_12m": round(used_12m, 3),
                "used_prior_12m": round(used_prior, 3),
                "last_used": last_used,
                "months_of_use": round(extra / rate, 1) if rate > 0 else None,
                "tier": _tier(needed, used_12m, used_prior),
            }
        )
    rows.sort(key=lambda r: -r["value"])
    return {"rows": rows, "totals": _totals(rows)}


# Ageing tiers, plainest first. Percentages are Finance's call, not set here.
TIERS = {
    "dead": "no demand, not used in 2 years",
    "idle": "no demand, not used in the last year",
    "slow": "no demand, but used in the last year",
    "over": "some demand, more on hand than it needs",
}


def _tier(needed, used_12m, used_prior):
    if needed > 1e-9:
        return "over"
    if used_12m > 0:
        return "slow"
    return "idle" if used_prior > 0 else "dead"


def _totals(rows):
    out = {"value": 0.0, "parts": len(rows), "by_kind": defaultdict(float),
           "by_tier": defaultdict(float), "by_basis": defaultdict(float)}
    for r in rows:
        out["value"] += r["value"]
        out["by_kind"][r["kind"]] += r["value"]
        out["by_tier"][r["tier"]] += r["value"]
        out["by_basis"][r["basis"]] += r["value"]
    return {
        "value": round(out["value"], 2),
        "parts": out["parts"],
        **{k: {kk: round(vv, 2) for kk, vv in out[k].items()} for k in ("by_kind", "by_tier", "by_basis")},
    }
