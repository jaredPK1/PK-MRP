"""The Analytics page's numbers: pure functions over what a run already has.

  * vendor_delivery -- from PK's own PO history: did each vendor deliver by
                       the date first asked (ORGDUE), how late when not, and
                       how long a PO really takes vs the lead time MAX holds
  * breakdown       -- today's buys by buyer, by vendor, by how late, and the
                       products whose orders they hold up
  * trend_point     -- one day's headline, appended to data/trend.json
  * impact          -- from the Decision Ledger: where what people did matched
                       the advice, what it protected and what it saved.

Impact is careful with its words. In shadow mode nobody is asked to follow
the advice, so a PO placed in time after a buy recommendation is "matched",
not "caused" -- the buyer may have placed it anyway. It is still the right
yardstick: the share matched, and the orders and dollars behind them, is
what going live should move.
"""

from collections import Counter, defaultdict
from datetime import date, timedelta
from statistics import median

import numpy as np
import pandas as pd

from .rank import _so_of

LATE_BUCKETS = (
    ("on time", 0, 0),
    ("1–10 days", 1, 10),
    ("11–30 days", 11, 30),
    ("31–90 days", 31, 90),
    ("over 90 days", 91, 10**6),
)


def _quarter(d):
    return f"{d.year} Q{(d.month - 1) // 3 + 1}"


def vendor_delivery(po_history, purchase_lt, vendor_names_by_id, today, months=24, quarters=12):
    """{"vendors": [...], "quarters": [...]} from received PO lines.

    A line counts when it has a first receipt and an original due date. On
    time = first receipt on or before ORGDUE (early counts). Real lead =
    working days from PO created to first receipt. `purchase_lt` {part: PURLT
    working days}."""
    df = po_history[
        po_history["first_receipt"].notna()
        & po_history["org_due"].notna()
        & po_history["created"].notna()
        & (po_history["vendor_id"] != "")
    ].copy()
    if df.empty:
        return {"vendors": [], "quarters": [], "since": None}
    first = df["first_receipt"].dt.normalize()
    df["late_days"] = (first - df["org_due"].dt.normalize()).dt.days
    df["on_time"] = df["late_days"] <= 0
    df["lead_wd"] = np.busday_count(
        df["created"].values.astype("datetime64[D]"), first.values.astype("datetime64[D]")
    )
    df["max_wd"] = df["part"].map(purchase_lt)
    df["received"] = first.dt.date

    since = today - timedelta(days=round(months * 30.44))
    recent = df[df["received"] >= since]
    vendors = []
    for vid, g in recent.groupby("vendor_id"):
        late = g.loc[~g["on_time"], "late_days"]
        maxlt = g["max_wd"].dropna()
        vendors.append(
            {
                "vendor": vendor_names_by_id.get(vid, vid),
                "lines": int(len(g)),
                "on_time_pct": round(100.0 * float(g["on_time"].mean()), 1),
                "late_lines": int(len(late)),
                "median_days_late": float(late.median()) if len(late) else 0.0,
                "real_lead_wd": float(g["lead_wd"].median()),
                "max_lead_wd": float(maxlt.median()) if len(maxlt) else None,
            }
        )
    vendors.sort(key=lambda v: -v["lines"])

    q_from = date(today.year - quarters // 4, today.month, 1)
    old = df[df["received"] >= q_from]
    qs = []
    for q, g in old.groupby(old["received"].map(_quarter)):
        qs.append(
            {
                "quarter": q,
                "lines": int(len(g)),
                "on_time_pct": round(100.0 * float(g["on_time"].mean()), 1),
            }
        )
    qs.sort(key=lambda r: r["quarter"])
    return {"vendors": vendors, "quarters": qs, "since": since.isoformat()}


def breakdown(buys, so_values=None, top=12):
    """Today's ranked buys, cut four ways. `buys` are snapshot buy dicts;
    `so_values` {so: USD} values the products' orders once each."""

    def roll(key):
        acc = defaultdict(lambda: {"buys": 0, "late": 0, "spend": 0.0, "orders": set()})
        for b in buys:
            for k in key(b):
                a = acc[k]
                a["buys"] += 1
                a["late"] += 1 if b["days_late"] > 0 else 0
                a["spend"] += b.get("spend") or 0.0
                a["orders"].update(b.get("sales_orders") or [])
        rows = [
            {
                "name": k,
                "buys": a["buys"],
                "late": a["late"],
                "spend": round(a["spend"], 2),
                "orders": len(a["orders"]),
            }
            for k, a in acc.items()
        ]
        rows.sort(key=lambda r: (-r["late"], -r["buys"], r["name"]))
        return rows

    lateness = Counter()
    for b in buys:
        d = b["days_late"]
        lateness[next(n for n, lo, hi in LATE_BUCKETS if lo <= d <= hi)] += 1
    # products: the part on each SO line a buy is pegged to, valued by those
    # orders once each
    held = defaultdict(lambda: {"buys": 0, "orders": set()})
    for b in buys:
        pegs = [p for p in b.get("pegs") or [] if p.get("root")]
        if pegs:  # each SO line's own product
            for p in pegs:
                so = _so_of(p["ref"])
                if so:
                    held[p["root"]]["orders"].add(so)
            for r in {p["root"] for p in pegs}:
                held[r]["buys"] += 1
            continue
        for r in b.get("for_parts") or []:
            held[r]["buys"] += 1
            held[r]["orders"].update(b.get("sales_orders") or [])
    so_values = so_values or {}
    products = sorted(
        (
            {
                "name": k,
                "buys": v["buys"],
                "value": round(sum(so_values.get(so, 0.0) for so in v["orders"]), 2),
            }
            for k, v in held.items()
        ),
        key=lambda r: (-r["value"], -r["buys"], r["name"]),
    )
    return {
        "by_buyer": roll(lambda b: [b.get("buyer") or "(no buyer)"]),
        "by_vendor": roll(lambda b: [b.get("vendor") or "(no vendor)"])[:top],
        "lateness": [{"name": n, "buys": lateness.get(n, 0)} for n, _lo, _hi in LATE_BUCKETS],
        "products": products[:top],
    }


TREND_KEYS = ("buy_now", "late", "orders_waiting", "order_value_waiting", "needs_source")


def trend_point(snap):
    h = snap.get("headline") or {}
    point = {k: h.get(k) for k in TREND_KEYS}
    point["overbuy_not_needed"] = ((snap.get("overbuys") or {}).get("totals") or {}).get(
        "not_needed"
    )
    return point


def impact(recs, outcomes, unit_cost, today, so_values=None):
    """What matched the advice, from ledger rows (dicts).

    recs: rec_id, kind, part, ref, qty, place_by, created_at, closed_at,
          sales_orders, order_values (from why_json) -- buys are counted per
          part, PO-line advice per PO line, and orders once each however
          many parts they wait on
    outcomes: rec_id, what, event_date, qty
    unit_cost: {part: $ per stocking unit}
    """
    by_rec = defaultdict(list)
    for o in outcomes:
        by_rec[o["rec_id"]].append(o)

    def first(ids, what):
        ids = ids if isinstance(ids, list) else [ids]
        dates = [
            _d(o["event_date"])
            for i in ids
            for o in by_rec.get(i, [])
            if o["what"] == what and o["event_date"]
        ]
        return min(dates) if dates else None

    buys = _episodes([r for r in recs if r["kind"] == "buy"])
    value = dict(so_values or {})
    for r in recs:
        for so, v in (r.get("order_values") or {}).items():
            value.setdefault(so, v)
    on_time, late, waiting, overdue = [], [], [], []
    days_to_act = []
    for r in buys:
        placed = first(r["rec_ids"], "po_placed")
        place_by = _d(r["place_by"])
        made = _d(r["created_at"])
        if placed:
            days_to_act.append(max((placed - made).days, 0))
            (on_time if place_by is None or placed <= place_by else late).append(r)
        elif place_by and place_by < today and not r.get("closed_at"):
            overdue.append(r)
        else:
            waiting.append(r)

    def orders(rows):
        sos = set().union(*(r["sales_orders"] for r in rows)) if rows else set()
        return len(sos), round(sum(value.get(so, 0.0) for so in sos), 2)

    def money(rows, what):
        hit = [r for r in rows if first(r["rec_ids"], what)]
        return len(hit), round(sum((r["qty"] or 0) * unit_cost.get(r["part"], 0.0) for r in hit), 2)

    pushes = _po_advice([r for r in recs if r["kind"] == "push_out"])
    cancels = _po_advice([r for r in recs if r["kind"] == "cancel"])
    expedites = _po_advice([r for r in recs if r["kind"] == "expedite"])
    pushed_n, pushed_usd = money(pushes, "po_pushed")
    cancelled_n, cancelled_usd = money(cancels, "po_cancelled")
    expedited_n = sum(1 for r in expedites if first(r["rec_ids"], "po_expedited"))
    protected_n, protected_usd = orders(on_time)
    risk_n, risk_usd = orders(overdue)
    return {
        "buys": len(buys),
        "placed_on_time": len(on_time),
        "placed_late": len(late),
        "not_placed_overdue": len(overdue),
        "not_due_yet": len(waiting),
        "orders_protected": protected_n,
        "order_value_protected": protected_usd,
        "orders_at_risk": risk_n,
        "order_value_at_risk": risk_usd,
        # past their order-by on the day they were first advised: lateness
        # PK-MRP inherited, not lateness after its advice
        "overdue_inherited": sum(
            1 for r in overdue if r["place_by"] and r["place_by"] < r["created_at"]
        ),
        "median_days_to_po": median(days_to_act) if days_to_act else None,
        "push_outs": len(pushes),
        "pushed": pushed_n,
        "pushed_usd": pushed_usd,
        "cancels": len(cancels),
        "cancelled": cancelled_n,
        "cancelled_usd": cancelled_usd,
        "expedites": len(expedites),
        "expedited": expedited_n,
        "first_day": min((_d(r["created_at"]) for r in recs), default=None),
    }


def _po_advice(recs):
    """One row per (part, PO line) for push-out / cancel / expedite advice."""
    by_ref = defaultdict(list)
    for r in recs:
        by_ref[(r["part"], r.get("ref"))].append(r)
    return [
        {
            "part": p,
            "ref": ref,
            "rec_ids": [r["rec_id"] for r in rows],
            "qty": max(r["qty"] or 0 for r in rows),
        }
        for (p, ref), rows in by_ref.items()
    ]


def _episodes(recs):
    """One row per part: the ledger writes a new recommendation whenever a
    buy's qty or dates change, so a part asked for all week is many rows but
    one piece of advice. Earliest start and order-by, largest order count."""
    by_part = defaultdict(list)
    for r in recs:
        by_part[r["part"]].append(r)
    out = []
    for part, rows in by_part.items():
        places = [_d(r["place_by"]) for r in rows if r["place_by"]]
        out.append(
            {
                "part": part,
                "rec_ids": [r["rec_id"] for r in rows],
                "created_at": min(_d(r["created_at"]) for r in rows),
                "place_by": min(places) if places else None,
                "sales_orders": set().union(*(r.get("sales_orders") or () for r in rows)),
                "closed_at": None if any(not r.get("closed_at") for r in rows) else 1,
            }
        )
    return out


def _d(v):
    if v is None or (isinstance(v, float) and v != v):
        return None
    if isinstance(v, pd.Timestamp):
        return v.date()
    if hasattr(v, "date") and callable(v.date):
        return v.date()
    return v if isinstance(v, date) else date.fromisoformat(str(v)[:10])
