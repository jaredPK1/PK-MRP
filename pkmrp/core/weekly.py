"""The end-of-week summary: what the week did to the plan, in one email.

Reads only what PK-MRP already keeps -- the daily trend, the latest
snapshot, the Done log and the Decision Ledger's impact -- so the email and
the Analytics page never disagree. Pure: build() returns plain data; the web
layer renders it and Pulse sends it.
"""

from datetime import date, timedelta

TREND = (
    ("buy_now", "Buys due this week", "count", "down"),
    ("late", "Already past order-by", "count", "down"),
    ("orders_waiting", "Booked orders waiting on a buy", "count", "down"),
    ("order_value_waiting", "Value of those orders", "money", "down"),
    ("needs_source", "Parts with no vendor", "count", "down"),
    ("overbuy_not_needed", "On open POs no order needs", "money", "down"),
)


def _week(today):
    """Monday..today of this week."""
    return today - timedelta(days=today.weekday()), today


def trend_rows(trend, today):
    """[(label, kind, start, now, delta, good)] from the first day of the
    week (or the latest day before it) to the latest day."""
    days = sorted(trend)
    if not days:
        return [], None, None
    monday, _ = _week(today)
    start_day = next((d for d in days if d >= monday.isoformat()), days[0])
    before = [d for d in days if d < monday.isoformat()]
    if before:
        start_day = before[-1]
    a, b = trend[start_day], trend[days[-1]]
    rows = []
    for key, label, kind, better in TREND:
        x, y = a.get(key), b.get(key)
        if x is None or y is None:
            continue
        delta = y - x
        good = None if not delta else ((delta < 0) == (better == "down"))
        rows.append({"key": key, "label": label, "kind": kind, "start": x, "now": y,
                     "delta": delta, "good": good})
    return rows, start_day, days[-1]


def done_week(log, today):
    """Done this week: totals, what MAX said, and by person."""
    monday, _ = _week(today)
    rows = [e for e in log if e["at"][:10] >= monday.isoformat()]
    by_check = {k: sum(1 for e in rows if e.get("check") == k)
                for k in ("confirmed", "no_po", "waiting", "undone")}
    people = {}
    for e in rows:
        if e.get("check") == "undone":
            continue
        who = e.get("owner") or e["by"].split("@")[0].split(".")[0].capitalize()
        people[who] = people.get(who, 0) + 1
    flagged = [e for e in rows if e.get("check") == "no_po"]
    return {"marked": len(rows) - by_check["undone"], **by_check,
            "by_person": sorted(people.items(), key=lambda kv: -kv[1]),
            "flagged": flagged[:8]}


def build(snap, trend, log, impact, today=None):
    """Everything the email shows, as plain data."""
    today = today or date.fromisoformat(snap["today"])
    monday, _ = _week(today)
    rows, start_day, end_day = trend_rows(trend or {}, today)
    buys = snap.get("buys") or []
    fx = snap.get("fix_max") or {}
    ecn = snap.get("ecn") or {}
    vd = (snap.get("analytics") or {}).get("vendor_delivery") or {}
    quarters = vd.get("quarters") or []
    return {
        "week_of": monday.isoformat(),
        "today": today.isoformat(),
        "trend": rows,
        "trend_from": start_day,
        "trend_to": end_day,
        "done": done_week(log or [], today),
        "impact": impact,
        "top": [
            {k: b.get(k) for k in ("part", "description", "qty", "days_late", "orders",
                                   "order_value", "vendor", "rank")}
            for b in buys[:5]
        ],
        "fix_max": (fx.get("counts") if fx.get("status") == "ok" else None),
        "obsolete_buys": len(ecn.get("obsolete_buys") or []),
        "ecn_status": ecn.get("status", "off"),
        "vendor_on_time": quarters[-2:] if quarters else [],
        "generated_at": snap.get("generated_at"),
    }
