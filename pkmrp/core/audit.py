"""Decision check: is the plan steering buyers well, and are buys landing well?

Runs after every plan (hourly) and keeps a little state between runs, so it
can see things a single plan can't:

  * repeat_po   -- the same part on two or more POs placed within two weeks
                   of each other in the last 30 days. Wasted work: one PO
                   would have done.
  * rebuy       -- the plan wants more of a part that got a PO in the last
                   two weeks. Either the PO was short of the need or demand
                   moved after it; the card says add to that PO.
  * jumped      -- a buy that appeared or grew sharply since the last run, or
                   whose need moved two weeks or more earlier. Buyers see a
                   "changed" chip before they act on it.
  * flip        -- a buy that showed up and went away again within a day with
                   no PO placed: noise the buyers may have chased.
  * sitting     -- late buys on the list for three days or more.
  * sizing      -- the sizer's own sanity: a small order on a cheap part with
                   more due within four weeks, or one very large order.

Each finding says what happened in buyer terms and what to do. A daily
trend line is kept so the weekly email and the page can show whether it's
getting better.

Pure: plain data in, (audit, new_state) out.
"""

from collections import defaultdict
from datetime import date, datetime, timedelta

REPEAT_WINDOW_DAYS = 14
REPEAT_LOOKBACK_DAYS = 30
REBUY_DAYS = 14
FLIP_HOURS = 24
SITTING_DAYS = 3
SITTING_LATE_DAYS = 10
JUMP_RATIO = 0.5
JUMP_MIN_UNITS = 3
JUMP_EARLIER_DAYS = 14
BIG_ORDER = 50000.0
KEEP_FLIPS_DAYS = 30
KEEP_TREND = 120


def _d(v):
    if v is None or v != v:
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    return date.fromisoformat(str(v)[:10])


def _t(v):
    return v if isinstance(v, datetime) else datetime.fromisoformat(str(v))


def recent_po_lines(open_pos, today, days=REPEAT_LOOKBACK_DAYS):
    """{part: [(po, created, qty, buyer)]} for open PO lines created lately,
    one entry per PO (a PO's deliveries add up)."""
    since = today - timedelta(days=days)
    acc = defaultdict(dict)
    for r in open_pos.itertuples(index=False):
        created = _d(r.created)
        if created is None or created < since:
            continue
        row = acc[r.part].setdefault(r.po, [r.po, created, 0.0, (r.buyer or "").strip()])
        row[2] += float(r.qty_due or 0)
    return {
        p: sorted((tuple(v) for v in pos.values()), key=lambda x: x[1]) for p, pos in acc.items()
    }


def repeat_pos(po_lines, descriptions, shelf=frozenset()):
    """Parts placed on 2+ POs within REPEAT_WINDOW_DAYS of each other."""
    out = []
    for part, pos in po_lines.items():
        if len(pos) < 2:
            continue
        clusters, cur = [], [pos[0]]
        for p in pos[1:]:
            if (p[1] - cur[-1][1]).days <= REPEAT_WINDOW_DAYS:
                cur.append(p)
            else:
                clusters.append(cur)
                cur = [p]
        clusters.append(cur)
        for c in clusters:
            if len(c) < 2:
                continue
            out.append(
                {
                    "check": "repeat_po",
                    "part": part,
                    "description": descriptions.get(part, ""),
                    "shelf": part in shelf,
                    "pos": [
                        {"po": po, "created": created, "qty": qty, "buyer": buyer}
                        for po, created, qty, buyer in c
                    ],
                    "total": sum(x[2] for x in c),
                    "what": f"{len(c)} POs in {(c[-1][1] - c[0][1]).days + 1} days for {sum(x[2] for x in c):g}",
                    "do": "One PO would have done. PK-MRP now sizes buys to cover several weeks of booked orders; if this keeps happening on a part, add a note or check its min/multiple in MAX.",
                }
            )
    out.sort(key=lambda f: f["pos"][-1]["created"], reverse=True)
    return out


def run_audit(snap, state, open_pos, today, now, shelf=frozenset(), descriptions=None):
    """(audit dict for the snapshot, new state to save)."""
    state = state or {}
    descriptions = descriptions or {}
    prev = state.get("buys") or {}
    buys = snap.get("buys") or []
    po_lines = recent_po_lines(open_pos, today)
    findings = []

    findings += repeat_pos(po_lines, descriptions, shelf)

    now_s = now.isoformat(timespec="minutes")
    cur = {}
    for b in buys:
        part = b["part"]
        p = prev.get(part)
        need = _d(b.get("need_by"))
        cur[part] = {
            "first_seen": p["first_seen"] if p else now_s,
            "last_seen": now_s,
            "qty": b["qty"],
            "min_qty": b.get("min_qty", b["qty"]),
            "need_by": need.isoformat() if need else None,
            "days_late": b.get("days_late", 0),
        }

        # rebuy: more wanted soon after a PO
        fresh = [x for x in po_lines.get(part, ()) if (today - x[1]).days <= REBUY_DAYS]
        if fresh:
            po, created, qty, buyer = fresh[-1]
            moved = p and p.get("need_by") and need and need < _d(p["need_by"])
            findings.append(
                {
                    "check": "rebuy",
                    "part": part,
                    "description": b.get("description", ""),
                    "po": po,
                    "po_created": created,
                    "po_qty": qty,
                    "buyer": buyer,
                    "want": b["qty"],
                    "what": f"PO {po} for {qty:g} placed {created.isoformat()}; the plan wants {b['qty']:g} more",
                    "cause": "demand moved earlier since the last run"
                    if moved
                    else "the PO was smaller than booked orders need",
                    "do": f"Add {b['qty']:g} to PO {po} rather than cutting a new PO, if the vendor will take it.",
                }
            )

        # jumped: new, grew sharply, or need moved much earlier since last run
        flag = None
        if p is None:
            if prev:  # the first run after a restart has nothing to compare
                flag = {"kind": "new", "text": "New on the list since the last plan"}
        else:
            grew = b["qty"] - p["qty"]
            if grew >= JUMP_MIN_UNITS and grew >= JUMP_RATIO * max(p["qty"], 1):
                flag = {
                    "kind": "grew",
                    "text": f"Went from {p['qty']:g} to {b['qty']:g} since the last plan",
                }
            if need and p.get("need_by"):
                earlier = (_d(p["need_by"]) - need).days
                if earlier >= JUMP_EARLIER_DAYS:
                    flag = {
                        "kind": "earlier",
                        "text": f"Needed {earlier} days sooner than the last plan said ({_d(p['need_by']).strftime('%b %-d')} → {need.strftime('%b %-d')})",
                    }
        if flag and flag["kind"] != "new":
            flag["at"] = now_s
            b["changed"] = flag
            findings.append(
                {
                    "check": "jumped",
                    "part": part,
                    "description": b.get("description", ""),
                    "what": flag["text"],
                    "do": "Open Why this buy? and check what moved before ordering — a re-dated order or a work order change can swing it back within hours.",
                }
            )
        elif flag:
            b["changed"] = dict(flag, at=now_s)

        # sitting: late and on the list for days
        first = _t(cur[part]["first_seen"])
        if b.get("days_late", 0) >= SITTING_LATE_DAYS and (now - first).days >= SITTING_DAYS:
            findings.append(
                {
                    "check": "sitting",
                    "part": part,
                    "description": b.get("description", ""),
                    "what": f"{b['days_late']} days past its order-by date, on the list since {first.date().isoformat()}",
                    "do": "Place it, or add a note (on hold, being quoted, ECN coming) so it stops coming back.",
                }
            )

        # sizing sanity
        sz = b.get("sizing") or {}
        uc = b.get("unit_cost") or 0
        lp = _d(sz.get("later_place_by"))
        if (
            sz.get("policy") == "minimum"
            and sz.get("cover_weeks") is not None
            and 0 < uc < 100
            and sz.get("later_qty")
            and lp
            and (lp - today).days <= 28
        ):
            findings.append(
                {
                    "check": "sizing",
                    "part": part,
                    "description": b.get("description", ""),
                    "what": f"Small order on a ${uc:,.2f} part with {sz['later_qty']:g} more due by {lp.isoformat()}",
                    "do": "Order the later quantity with it (4-week order link on the card).",
                }
            )
        if (b.get("spend") or 0) >= BIG_ORDER and sz.get("policy") == "economic":
            findings.append(
                {
                    "check": "sizing",
                    "part": part,
                    "description": b.get("description", ""),
                    "what": f"Covering {sz.get('cover_weeks'):g} weeks makes this a ${b['spend']:,.0f} order",
                    "do": f"Fine if the vendor's pricing rewards it; otherwise order the minimum ({b.get('min_qty', 0):g}).",
                }
            )

    # flips: buys that were here and are gone with no PO placed since
    flips = [f for f in state.get("flips", []) if (today - _d(f["gone"])).days <= KEEP_FLIPS_DAYS]
    for part, p in prev.items():
        if part in cur:
            continue
        first = _t(p["first_seen"])
        if (now - first).total_seconds() > FLIP_HOURS * 3600:
            continue
        placed = [x for x in po_lines.get(part, ()) if x[1] >= first.date()]
        if placed:
            continue  # it went because someone ordered it -- that's the point
        flips.append(
            {
                "part": part,
                "description": descriptions.get(part, ""),
                "appeared": p["first_seen"],
                "gone": now_s,
                "qty": p["qty"],
            }
        )
    for f in flips:
        if (now - _t(f["gone"])).total_seconds() <= FLIP_HOURS * 3600:
            findings.append(
                {
                    "check": "flip",
                    "part": f["part"],
                    "description": f.get("description", ""),
                    "what": f"Asked for {f['qty']:g} at {f['appeared'][11:16]} on {f['appeared'][:10]}, gone by {f['gone'][11:16]} with no PO",
                    "do": "Nothing to buy. If someone ordered it in that window, check the PO is still needed.",
                }
            )

    counts = defaultdict(int)
    for f in findings:
        counts[f["check"]] += 1
    pos_placed = sum(len(v) for v in po_lines.values())
    repeat_lines = sum(len(f["pos"]) - 1 for f in findings if f["check"] == "repeat_po")
    trend = [t for t in state.get("trend", []) if t["date"] != today.isoformat()]
    point = {
        "date": today.isoformat(),
        "pos_30d": pos_placed,
        "extra_pos_30d": repeat_lines,
        **dict(counts),
    }
    trend = (trend + [point])[-KEEP_TREND:]
    audit = {
        "at": now_s,
        "counts": dict(counts),
        "pos_30d": pos_placed,
        "extra_pos_30d": repeat_lines,
        "findings": findings,
        "trend": trend,
    }
    new_state = {"buys": cur, "flips": flips, "trend": trend}
    return audit, new_state
