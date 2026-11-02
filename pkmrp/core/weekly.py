"""The Monday digest: everything that needs someone this week, in one email.

Top: "Needs you this week" -- a short list per kind, in a fixed order of
urgency (buys past their order-by, parts going obsolete with nothing to
cover them, Done that MAX doesn't show, recent overbuys, price issues, repeat
POs, safety stock to restore, buys on ECN-obsoleted parts), each line linking to the page that
explains it. "New" = not in last Monday's email: the keys every section
showed are saved with the send (weekly_sent.seen) and compared next time.
Below: last week in numbers (trend, Done, the ledger) and housekeeping.

It replaces the Friday summary and the per-part EOL emails, which went out
once an hour while the distributor lookups worked through the parts list.

Reads only what PK-MRP already keeps -- the snapshot, eol.json,
vendor_prices.json, the daily trend, the Done log and the Decision Ledger's
impact -- so the email and the pages never disagree. Pure: build() returns
plain data; the web layer filters (held, cleared, reviewed), renders it and
pk-notify sends it.
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


SHOW = 5  # lines per section; the link has the rest


def _start(today):
    """The digest looks back seven days."""
    return today - timedelta(days=7)


def trend_rows(trend, today):
    """[(label, kind, start, now, delta, good)] from a week ago (the latest
    day on or before it, else the first day) to the latest day."""
    days = sorted(trend)
    if not days:
        return [], None, None
    start = _start(today).isoformat()
    before = [d for d in days if d <= start]
    start_day = before[-1] if before else days[0]
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
    """Done in the last seven days: totals, what MAX said, and by person."""
    start = _start(today).isoformat()
    rows = [e for e in log if e["at"][:10] > start]
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


LABELS = {"buys": "buys to place", "eol": "parts going obsolete", "done_check": "done but not in MAX",
          "overbuys": "recent overbuys", "prices": "price issues", "repeat": "repeat POs",
          "ecn": "buys on ECN-obsoleted parts", "safety": "safety stock buys"}


def _section(key, title, why, link, rows, seen, total=None):
    """rows: [{key, ...}] already in priority order. New ones go first."""
    before = seen.get(key) if seen else None
    for r in rows:
        r["new"] = before is not None and r["key"] not in before
    ordered = sorted(rows, key=lambda r: not r["new"])
    return {
        "key": key, "title": title, "label": LABELS.get(key, title.lower()), "why": why, "link": link,
        "total": len(rows) if total is None else total,
        "new": sum(1 for r in rows if r["new"]),
        "items": ordered[:SHOW],
        "keys": [r["key"] for r in rows],
    }


def _ecn_no(e):
    return e.get("ecn", "") if isinstance(e, dict) else (e or "")


def _alternate_line(i):
    alts = [a for a in i.get("alternates") or [] if a["status"] != "bad"]
    if not alts:
        return ""
    a = alts[0]
    said = {"active": "active at distributors", "unknown": "status unknown",
            "unchecked": "not checked yet"}[a["status"]]
    return f"MAX approves {a['mpn']} ({a['maker'] or 'maker not on file'}, {said}) — check it before a last-time buy"


def priorities(snap, today, eol_items=(), price_alerts=(), overbuy_rows=(), done=None,
               seen=None, price_key=None, overbuy_key=None):
    """The "Needs you this week" sections, most urgent kind first; empty
    sections are left out. The caller has already taken out held parts,
    cleared overbuys and reviewed alerts."""
    week_end = (today + timedelta(days=7)).isoformat()
    out = []

    all_buys = [b for b in snap.get("buys") or [] if (b.get("place_by") or "") <= week_end]
    buys = [b for b in all_buys if not b.get("ss_only")]
    ss_buys = [b for b in all_buys if b.get("ss_only")]
    out.append(_section(
        "buys", "Buys to place", "Order-by date is this week or already past.", "/buys",
        [{"key": b["part"], "part": b["part"], "description": b.get("description", ""),
          "money": b.get("order_value") or 0, "money_label": "orders waiting",
          "detail": " · ".join(x for x in (
              f"{b.get('qty', 0):g} from {(b.get('vendor') or 'no vendor').title()}",
              f"{b['days_late']}d late" if b.get("days_late") else "due this week",
              f"{b.get('orders') or 0} order{'s' if b.get('orders') != 1 else ''}",
          ) if x),
          "link": f"/buys?q={b['part']}"} for b in buys], seen,
        total=len(buys)))

    words = {"obsolete": "Obsolete", "eol": "End of life", "last_time_buy": "Last-time buy"}
    out.append(_section(
        "eol", "Parts going obsolete", "Booked orders need them and stock doesn't cover them.", "/eol",
        [{"key": f"{i['part']}|{i['kind']}", "part": i["part"], "description": i.get("description", ""),
          "money": i.get("ltb_cost") or 0, "money_label": "last-time buy",
          "detail": f"{words.get(i['kind'], i['kind'])} — {(i.get('signals') or [{}])[0].get('detail', '')}"
                    f" · booked {i['booked']:g}, have {i['on_hand'] + i['on_order']:g}"
                    f" · last-time buy {i['ltb_qty']:g}",
          "extra": _alternate_line(i),
          "link": f"/eol?q={i['part']}"}
         for i in eol_items if i.get("tier") == "act"], seen))

    flagged = (done or {}).get("flagged") or []
    out.append(_section(
        "done_check", "Marked done, MAX still needs it", "Marked done in PK-MRP, but MAX shows no PO covering it.",
        "/done",
        [{"key": f"{e['part']}|{e['at']}", "part": e["part"], "description": "",
          "detail": f"marked by {e.get('owner') or e['by'].split('@')[0]}"
                    + (f", PO {e['po']}" if e.get("po") else ", no PO given"),
          "link": "/done"} for e in flagged], seen))

    obs = sorted((r for r in overbuy_rows if r.get("new")), key=lambda r: -(r.get("value") or 0))
    out.append(_section(
        "overbuys", "Recent overbuys", "POs placed in the last 30 days that no booked order needs (yet).",
        "/overbuys?new=1",
        [{"key": overbuy_key(r) if overbuy_key else f"PO|{r['part']}|{r.get('ref')}",
          "part": r["part"], "description": r.get("description", ""),
          "money": r.get("value") or 0, "money_label": "on the PO",
          "detail": f"{r.get('what', '')} · {r.get('ref', '')} · {(r.get('vendor') or '').title()}",
          "link": f"/overbuys?new=1&q={r['part']}"} for r in obs], seen))

    pa = sorted(price_alerts, key=lambda a: -(a.get("impact") or 0))
    out.append(_section(
        "prices", "Price issues", "Paying more than last year, than standard, or than another vendor.",
        "/vendor-prices",
        [{"key": price_key(a) if price_key else f"{a['kind']}|{a['vendor_id']}|{a.get('part') or ''}",
          "part": a.get("part") or "", "vendor": (a.get("vendor") or "").title(),
          "description": (a.get("vendor") or "").title() if a.get("part") else "",
          "money": a.get("impact") or 0, "money_label": "at stake",
          "detail": a.get("what", ""),
          "link": f"/vendor-prices?v={a['vendor_id']}" + (f"&part={a['part']}" if a.get("part") else "")}
         for a in pa], seen))

    reps = [f for f in (snap.get("audit") or {}).get("findings") or [] if f.get("check") == "repeat_po"]
    out.append(_section(
        "repeat", "Repeat POs", "Several POs in a few days for a part one PO would have covered.", "/check",
        [{"key": f"{f['part']}|{(f.get('pos') or [{}])[-1].get('po', '')}", "part": f["part"],
          "description": f.get("description", ""), "detail": f.get("what", ""), "link": "/check"}
         for f in reps], seen))

    ss_buys.sort(key=lambda b: -(b.get("spend") or 0))
    out.append(_section(
        "safety", "Safety stock to restore",
        "Nothing booked needs these this week; stock is below the safety stock PK-MRP trusts.",
        "/buys?q=safety+stock",
        [{"key": b["part"], "part": b["part"], "description": b.get("description", ""),
          "money": b.get("spend") or 0, "money_label": "to buy",
          "detail": f"{b.get('qty', 0):g} from {(b.get('vendor') or 'no vendor').title()}"
                    f" · safety stock {(b.get('ss_judge') or {}).get('use', b.get('safety_stock', 0)):g}",
          "link": f"/buys?q={b['part']}"} for b in ss_buys], seen))

    ecn = snap.get("ecn") or {}
    out.append(_section(
        "ecn", "Buys on ECN-obsoleted parts", "Engineering obsoleted the part; check before placing.",
        "/fix-max",
        [{"key": x.get("part", ""), "part": x.get("part", ""), "description": x.get("description", ""),
          "money": x.get("order_value") or 0, "money_label": "orders waiting",
          "detail": f"ECN {_ecn_no(x.get('ecn'))} · {x.get('orders') or 0} orders", "link": "/fix-max"}
         for x in ecn.get("obsolete_buys") or [] if isinstance(x, dict)], seen))

    return [s for s in out if s["total"]]


def build(snap, trend, log, impact, today=None, sections=None):
    """Everything the email shows, as plain data. `sections` from priorities()."""
    today = today or date.fromisoformat(snap["today"])
    monday = today - timedelta(days=today.weekday())
    rows, start_day, end_day = trend_rows(trend or {}, today)
    fx = snap.get("fix_max") or {}
    ecn = snap.get("ecn") or {}
    vd = (snap.get("analytics") or {}).get("vendor_delivery") or {}
    quarters = vd.get("quarters") or []
    sections = sections or []
    return {
        "week_of": monday.isoformat(),
        "today": today.isoformat(),
        "sections": sections,
        "new_total": sum(s["new"] for s in sections),
        "seen": {s["key"]: s["keys"] for s in sections},
        "trend": rows,
        "trend_from": start_day,
        "trend_to": end_day,
        "done": done_week(log or [], today),
        "impact": impact,
        "fix_max": (fx.get("counts") if fx.get("status") == "ok" else None),
        "prices": snap.get("vendor_prices") or {},
        "audit": {
            "pos_30d": (snap.get("audit") or {}).get("pos_30d", 0),
            "extra_pos_30d": (snap.get("audit") or {}).get("extra_pos_30d", 0),
        },
        "ecn_status": ecn.get("status", "off"),
        "vendor_on_time": quarters[-2:] if quarters else [],
        "generated_at": snap.get("generated_at"),
    }
