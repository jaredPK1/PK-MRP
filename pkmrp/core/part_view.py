"""Part lookup: one part, PK-MRP's plan and MAX's MRP side by side.

Chad asked for it on 11-06: PCAs are changing vendors, so he'll buy a little
ahead of demand -- and the demand PK-MRP shows for a PCA isn't the demand
MAX MRP shows. Both start from the same stock and open POs; they differ in
what they count as demand:

  PK-MRP  booked sales orders and open WOs, exploded through the BOM
          (builds of parents it plans), plus safety stock where it judges
          MAX's number sound.
  MAX     the same booked orders and WOs, plus its own planned orders for
          the parents -- which carry master-schedule (forecast) entries,
          MAX's safety stock and order policies down the bill. On 11-06,
          96% of MAX's PCA demand came from those parent planned orders.

This puts the two in the same buckets over the same window so the gap has
a name. Pure: the snapshot's per-part rows in, a dict out.
"""

from datetime import date, timedelta

# PK-MRP ledger kinds -> bucket
PK_BUCKET = {
    "so": "orders",
    "wo_req": "wos",
    "planned_make": "parents",
    "planned_kit": "parents",
    "po_kit": "kits",
    "sub_req": "kits",
    "safety_stock": "safety",
}
# MAX Order_Master type of the order a requirement belongs to -> bucket
MAX_BUCKET = {"CU": "orders", "MF": "wos", "PL": "parents", "MS": "forecast", "SO": "kits"}

BUCKETS = (
    ("orders", "Sales orders"),
    ("wos", "Open work orders"),
    ("parents", "Builds of parent assemblies (planned, not released)"),
    ("forecast", "Master schedule (forecast) entries"),
    ("kits", "Subcontract kits"),
    ("safety", "Safety stock"),
)

HORIZONS = {"3": 91, "6": 182, "12": 365, "all": None}


def _d(v):
    if v is None or v == "":
        return None
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:  # "NaT" from a blank MAX date
        return None


def _within(when, until):
    return until is None or when is None or when <= until


def compare(entry, today, horizon="6"):
    """Both plans for one part over the window: demand by bucket, supply,
    what each says to buy, and the running balance PK-MRP sees.

    entry  the part's row from part_plans.json
    """
    days = HORIZONS.get(horizon, HORIZONS["6"])
    until = today + timedelta(days=days) if days else None
    pk = {k: 0.0 for k, _ in BUCKETS}
    mx = {k: 0.0 for k, _ in BUCKETS}
    on_hand, pos, wos = 0.0, 0.0, 0.0
    timeline = []
    for when, qty, kind, ref in entry.get("pk", []):
        when = _d(when)
        if kind == "on_hand":
            on_hand += qty
            continue
        if not _within(when, until):
            continue
        if kind == "po":
            pos += qty
        elif kind == "wo":
            wos += qty
        elif kind in PK_BUCKET and qty < 0:
            pk[PK_BUCKET[kind]] += -qty
        # "planned_*" with a + qty is this part's own planned order (not
        # supply yet); with a - qty it's a planned parent build drawing on it
        if not (kind.startswith("planned_") and qty > 0):
            timeline.append((when, qty, kind, ref))
    # MAX's safety stock is a floor its planned orders refill, not a dated need
    mx["safety"] = float((entry.get("info") or {}).get("max_ss") or 0.0)
    for when, qty, src, ord_, parent, ref in entry.get("max_dem", []):
        if _within(_d(when), until):
            mx[MAX_BUCKET.get(src, "kits")] += qty

    pk_buys = [b for b in entry.get("pk_buys", []) if _within(_d(b[1]), until)]
    mx_buys = [b for b in entry.get("max_pl", []) if _within(_d(b[0]), until)]

    # running balance through PK-MRP's firm supply and demand (no planned buys)
    timeline.sort(key=lambda e: (e[0] or date.min, e[1] < 0))
    bal, rows, short_on = on_hand, [], None
    for when, qty, kind, ref in timeline:
        bal += qty
        rows.append({"date": when, "qty": qty, "kind": kind, "ref": ref, "balance": round(bal, 3)})
        if bal < -1e-9 and short_on is None:
            short_on = when

    pk_total = sum(pk.values())
    mx_total = sum(mx.values())
    gaps = sorted(
        ((k, label, mx[k] - pk[k]) for k, label in BUCKETS if abs(mx[k] - pk[k]) > 1e-6),
        key=lambda g: -abs(g[2]),
    )
    return {
        "horizon": horizon,
        "until": until,
        "buckets": [
            {"key": k, "label": label, "pk": round(pk[k], 3), "max": round(mx[k], 3)}
            for k, label in BUCKETS
            if pk[k] or mx[k]
        ],
        "pk_demand": round(pk_total, 3),
        "max_demand": round(mx_total, 3),
        "gap": round(mx_total - pk_total, 3),
        "biggest_gap": gaps[0] if gaps else None,
        "on_hand": round(on_hand, 3),
        "on_po": round(pos, 3),
        "on_wo": round(wos, 3),
        "pk_buy_qty": round(sum(b[2] for b in pk_buys), 3),
        "max_buy_qty": round(sum(b[1] for b in mx_buys), 3),
        "pk_buys": pk_buys,
        "max_buys": mx_buys,
        "timeline": rows,
        "short_on": short_on,
    }
