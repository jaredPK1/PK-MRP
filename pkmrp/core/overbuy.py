"""Overbuys: money committed beyond what booked orders need.

Replaces someone hunting through open POs and stock for what was bought
against a forecast that never came. For everyday (order-driven) parts only --
committed parts buy ahead on purpose and are left out.

  * open POs nobody needs, or not yet -- the netting's cancel candidates
    (no booked order nets against the line), excess on PO (part of the line
    is needed, the rest isn't) and push-outs (needed, but well after it
    lands), valued at unit cost, with buyer, vendor and when it was placed;
  * stock no booked order needs -- bought parts on hand beyond every open
    demand netted against them;
  * by buyer -- totals, for coaching, never a ranking of people.

Pure.
"""

from collections import defaultdict

KINDS = {
    "cancel_candidate": "not needed",
    "excess_on_po": "more than needed",
    "push_out_open_po": "arrives early",
}


def overbuys(
    exceptions, open_pos, demands, stock, parts, segments, vendor_name, today, new_days=30
):
    seg = {r["part"]: r["segment"] for r in segments}
    lines = {f"PO {r.po}/{r.line}/{r.delivery}": r for r in open_pos.itertuples(index=False)}

    def cost(p):
        return float(parts[p].unit_cost or 0) if p in parts else 0.0

    po_rows = []
    for e in exceptions:
        if (
            e.kind not in KINDS
            or not e.ref.startswith("PO ")
            or seg.get(e.part) in ("committed", "unproven_long")
        ):
            continue
        line = lines.get(e.ref)
        created = line.created.date() if line is not None and line.created == line.created else None
        due = line.cur_due.date() if line is not None and line.cur_due == line.cur_due else None
        po_rows.append(
            {
                "part": e.part,
                "description": parts[e.part].description if e.part in parts else "",
                "ref": e.ref,
                "what": KINDS[e.kind],
                "kind": e.kind,
                "qty": round(e.qty, 3),
                "value": round(e.qty * cost(e.part), 2),
                "buyer": (line.buyer if line is not None else "") or "",
                "vendor": vendor_name.get(e.part, ""),
                "placed": created,
                "due": due,
                "new": bool(created and (today - created).days <= new_days),
                "days_early": e.days if e.kind == "push_out_open_po" else None,
            }
        )
    po_rows.sort(key=lambda r: -r["value"])

    need = defaultdict(float)
    for p, ds in demands.items():
        need[p] += sum(d.qty for d in ds)
    stock_rows = []
    for p, q in stock.items():
        info = parts.get(p)
        if not info or info.type != "B" or seg.get(p) in ("committed", "unproven_long"):
            continue
        extra = q - need.get(p, 0.0)
        if extra <= 1e-9 or cost(p) <= 0:
            continue
        stock_rows.append(
            {
                "part": p,
                "description": info.description,
                "buyer": info.buyer,
                "on_hand": q,
                "needed": round(need.get(p, 0.0), 3),
                "extra": round(extra, 3),
                "value": round(extra * cost(p), 2),
                "idle": need.get(p, 0.0) <= 0,
            }
        )
    stock_rows.sort(key=lambda r: -r["value"])

    by_buyer = defaultdict(lambda: {"po_value": 0.0, "po_lines": 0, "new_value": 0.0})
    for r in po_rows:
        b = by_buyer[r["buyer"] or "(none)"]
        b["po_value"] += r["value"]
        b["po_lines"] += 1
        if r["new"]:
            b["new_value"] += r["value"]

    return {
        "po": po_rows[:400],
        "stock": stock_rows[:300],
        "by_buyer": sorted(
            (
                {
                    "buyer": k,
                    **{kk: round(vv, 2) if isinstance(vv, float) else vv for kk, vv in v.items()},
                }
                for k, v in by_buyer.items()
            ),
            key=lambda x: -x["po_value"],
        ),
        "totals": _totals(po_rows, stock_rows),
        "new_days": new_days,
    }


def _totals(po_rows, stock_rows):
    def total(rows):
        return round(sum(r["value"] for r in rows), 2)

    new = [r for r in po_rows if r["new"] and r["kind"] != "push_out_open_po"]
    return {
        "not_needed": total(r for r in po_rows if r["kind"] == "cancel_candidate"),
        "more_than_needed": total(r for r in po_rows if r["kind"] == "excess_on_po"),
        "early": total(r for r in po_rows if r["kind"] == "push_out_open_po"),
        "new": total(new),
        "new_lines": len(new),
        "stock_extra": total(stock_rows),
        "stock_idle": total(r for r in stock_rows if r["idle"]),
    }
