"""The planning run, frozen to JSON for the web app.

`pkmrp run` writes data/latest.json and data/history/<date>.json; pages read
them, so a page never waits on MAX. History is what makes progress visible
("6 buys came off the list since yesterday").

Interim: these files live in the app's data volume until the mrp_* tables
exist in PK_Ops (DBA script), at which point the Decision Ledger takes over.
"""

import json
import os
import tempfile
from collections import Counter
from datetime import date, datetime

import pandas as pd

from .core.analytics import breakdown, trend_point
from .core.order_qty import size_all
from .core.overbuy import overbuys
from .core.params import purlt_proposals
from .core.rank import buy_list
from .core.story import build_story
from .core.vendor_order import recent_open_pos, vendor_plan

DATA_DIR = os.environ.get("DATA_DIR", os.path.join(os.getcwd(), "data"))


def _iso(v):
    return v.isoformat() if isinstance(v, (date, datetime)) else v


def _iso_deep(v):
    """Dates to ISO strings, all the way down."""
    if isinstance(v, dict):
        return {k: _iso_deep(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_iso_deep(x) for x in v]
    return _iso(v)


def so_lines_meta(so_df, settings):
    """{so: {'customer', 'value' (USD), 'lines': {line: ship date}}} for stories."""
    values, customers = so_rollups(so_df)
    out = {}
    col = settings.demand_date
    for r in so_df.itertuples(index=False):
        m = out.setdefault(
            r.so,
            {
                "customer": customers.get(r.so, ""),
                "value": round(values.get(r.so, 0.0), 2),
                "lines": {},
            },
        )
        due = getattr(r, col, None)
        due = due if due == due else r.cur_due
        if due is not None and due == due:
            m["lines"][r.line] = due.date() if hasattr(due, "date") else due
    return out


def so_rollups(so_df):
    """({so: open value in USD}, {so: customer}). Non-USD orders count 0 until
    the exchange-rate convention is confirmed, rather than adding yen to dollars."""
    values, customers = Counter(), {}
    for r in so_df.itertuples(index=False):
        customers[r.so] = r.customer
        cur = (r.currency or "").upper()
        price = r.unit_price if r.unit_price == r.unit_price else 0.0
        if cur in ("", "USD", "US$", "$"):
            values[r.so] += float(price or 0) * float(r.qty_due or 0)
    return dict(values), customers


def build(run, so_df):
    res, today = run["result"], run["today"]
    so_values, so_customers = so_rollups(so_df)
    buys = buy_list(
        res.planned,
        run["parts"],
        run["lead_times"],
        so_values,
        so_customers,
        today,
        vendor_name=run.get("vendor_name"),
        exclude=frozenset(run.get("shelf") or ()),
    )
    by_kind = Counter(e.kind for e in res.exceptions)
    so_meta = so_lines_meta(run["so_lines"], run["settings"])
    receipts_by_part = {}
    for r in run["receipts"]:
        receipts_by_part.setdefault(r.part, []).append((r.date, r.qty, r.ref))
    parts = run["parts"]

    def describe(p):
        return parts[p].description if p in parts else ""

    late_by_part = Counter(e.part for e in res.exceptions if e.kind == "late_to_place")
    committed = {r["part"] for r in run.get("segments") or [] if r["segment"] == "committed"}
    size_all(buys, res.planned, res.demands, parts, run["open_pos"], committed, run["settings"], today)
    for b in buys:
        part = b["part"]
        sz = b["sizing"]
        b["story"] = _iso_deep(
            build_story(
                part,
                res.demands.get(part, []),
                receipts_by_part.get(part, []),
                run["stock"].get(part, 0.0),
                b["qty"],
                b["lead_days"],
                b["lead_source"],
                b["vendor"],
                today,
                describe,
                so_meta,
                later_buys=[(sz["later_place_by"], sz["later_qty"])] if sz["later_qty"] else [],
            )
        )
        b["late_lines"] = late_by_part.get(part, 0)
        b["pegs"] = [
            {"ref": p.ref, "root": p.root_part}
            for o in res.planned
            if o.part == part and o.kind == "buy"
            for p in o.pegs
        ][:60]
    # No PO ever, no approved vendor, no store in the description: the dates
    # rest on MAX's default lead time and nobody can place it yet. A buyer
    # quotes these; they don't belong in the ranked list.
    needs_source = [b for b in buys if not b["vendor"]]
    buys = [b for b in buys if b["vendor"]]
    for i, b in enumerate(buys, 1):
        b["rank"] = i
    needs_source.sort(key=lambda b: (-b["order_value"], b["need_by"], b["part"]))
    unscheduled = run["worklists"]["unscheduled"]
    segments = run.get("segments") or []
    seg_counts = Counter(r["segment"] for r in segments)
    params = purlt_proposals(run["parts"], run["lead_times"], segments)
    names = run.get("vendor_name") or {}
    for r in params:
        r["vendor"] = names.get(r["part"], r["vendor"])
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "today": today.isoformat(),
        "mode": "shadow",
        "counts": run["counts"],
        "timings": run["timings"],
        "exceptions": dict(by_kind),
        "headline": {
            "buy_now": len(buys),
            "late": sum(1 for b in buys if b["days_late"] > 0),
            "orders_waiting": len({so for b in buys for so in b["sales_orders"]}),
            "order_value_waiting": round(
                sum(so_values.get(so, 0) for so in {so for b in buys for so in b["sales_orders"]}),
                2,
            ),
            "expedites": by_kind.get("expedite_open_po", 0),
            "push_outs": by_kind.get("push_out_open_po", 0),
            "cancel_candidates": by_kind.get("cancel_candidate", 0),
            "beyond_backlog": by_kind.get("beyond_backlog", 0),
            "unscheduled_lines": len(unscheduled),
            "unplannable_lines": len(run["worklists"]["unplannable"]),
            "consigned_pairs": run["counts"].get("consigned_pairs", 0),
            "committed": seg_counts.get("committed", 0),
            "unproven_long": seg_counts.get("unproven_long", 0),
            "lead_time_fixes": len(params),
            "needs_source": len(needs_source),
        },
        "buys": [{k: _iso(v) for k, v in b.items()} for b in buys],
        "needs_source": [{k: _iso(v) for k, v in b.items()} for b in needs_source],
        "segments": [r for r in segments if r["segment"] != "order_driven"],
        "segment_counts": dict(seg_counts),
        "params": params,
        "committed_plans": [_iso_deep(cp) for cp in run.get("committed_plans", [])],
        "pipeline": _iso_deep(run.get("pipeline") or {"status": "off"}),
        "shelf_orders": _iso_deep(run.get("shelf_orders") or []),
        # USD value of each open SO a buy holds up, so counts across buys
        # can add orders once (Analytics, the Decision Ledger's why)
        "so_values": {
            so: round(so_values.get(so, 0.0), 2) for b in buys for so in b["sales_orders"]
        },
        "analytics": {
            "vendor_delivery": run.get("vendor_delivery") or {},
            "breakdown": breakdown([{k: _iso(v) for k, v in b.items()} for b in buys], so_values),
        },
        "vendor_plan": _iso_deep(
            vendor_plan(
                res.planned,
                run["parts"],
                run.get("vendor_name") or {},
                run.get("vendor_part") or {},
                so_values,
                so_customers,
                today,
            )
        ),
        "vendor_pos": _iso_deep(
            recent_open_pos(run["open_pos"], run.get("vendor_names_by_id") or {}, today)
        ),
        "ecn": _ecn(run, buys, needs_source),
        "replaced": _iso_deep(run.get("replaced") or {}),
        "fix_max": _iso_deep(run.get("fix_max") or {"status": "off"}),
        # open POs placed in the last 60 days, by part: lets a Done's PO
        # number be matched to MAX
        "recent_po_parts": _recent_po_parts(run["open_pos"], today),
        "overbuys": _iso_deep(
            overbuys(
                [e for e in res.exceptions if e.part not in (run.get("shelf") or {})],
                run["open_pos"],
                res.demands,
                {p: q for p, q in run["stock"].items() if p not in (run.get("shelf") or {})},
                run["parts"],
                run.get("segments", []),
                run.get("vendor_name") or {},
                today,
            )
        ),
    }


def _ecn(run, buys, needs_source):
    """ECN facts for the parts this plan touches, and buys of obsoleted parts."""
    from .core.ecn import by_part, obsolete_buys

    src = run.get("ecn") or {"status": "off"}
    if src.get("status") != "ok":
        return {k: v for k, v in src.items() if k != "rows"}
    res = run["result"]
    keep = set(res.demands) | {p for p, q in run["stock"].items() if q} | set(run["open_pos"]["part"])
    keep |= {cp["part"] for cp in run.get("committed_plans", [])}
    parts = by_part(src["rows"], keep)
    flat = [{k: _iso(v) for k, v in b.items()} for b in buys + needs_source]
    return {
        "status": "ok",
        "parts": parts,
        "obsolete_buys": obsolete_buys(flat, parts),
        "open_parts": sum(1 for v in parts.values() if v["open"]),
        "obsolete_parts": sum(1 for v in parts.values() if v["obsolete"]),
    }


def _recent_po_parts(open_pos, today, days=60):
    out = {}
    cutoff = pd.Timestamp(today) - pd.Timedelta(days=days)
    for r in open_pos.itertuples(index=False):
        if r.created == r.created and r.created >= cutoff:
            out.setdefault(r.part, []).append([r.po, r.created.date().isoformat(), float(r.qty_due)])
    return out


def write(snap):
    os.makedirs(os.path.join(DATA_DIR, "history"), exist_ok=True)
    payload = json.dumps(snap, default=str, separators=(",", ":"))
    for path in (
        os.path.join(DATA_DIR, "latest.json"),
        os.path.join(DATA_DIR, "history", f"{snap['today']}.json"),
    ):
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".snap-")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
        os.replace(tmp, path)
    _add_trend(snap)


def _add_trend(snap):
    """data/trend.json: {day: headline numbers}, the last plan of each day.
    Started from the history snapshots when it doesn't exist yet."""
    path = os.path.join(DATA_DIR, "trend.json")
    trend = load_trend()
    if not trend:
        hist = os.path.join(DATA_DIR, "history")
        for f in sorted(os.listdir(hist)):
            if f.endswith(".json") and f[:-5] != snap["today"]:
                try:
                    with open(os.path.join(hist, f), encoding="utf-8") as fh:
                        trend[f[:-5]] = trend_point(json.load(fh))
                except (OSError, ValueError):
                    continue
    trend[snap["today"]] = trend_point(snap)
    fd, tmp = tempfile.mkstemp(dir=DATA_DIR, prefix=".trend-")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(trend, fh, sort_keys=True)
    os.replace(tmp, path)


def load_trend():
    try:
        with open(os.path.join(DATA_DIR, "trend.json"), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def load_latest():
    try:
        with open(os.path.join(DATA_DIR, "latest.json"), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def load_audit_state():
    try:
        with open(os.path.join(DATA_DIR, "audit_state.json"), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def write_audit_state(state):
    os.makedirs(DATA_DIR, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=DATA_DIR, prefix=".audit-")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(_iso_deep(state), fh, separators=(",", ":"), default=str)
    os.replace(tmp, os.path.join(DATA_DIR, "audit_state.json"))


def add_audit(snap, run):
    """Run the decision check against the last run's state; never fail the plan."""
    from .core.audit import run_audit

    try:
        parts = run["parts"]
        audit, state = run_audit(
            snap,
            load_audit_state(),
            run["open_pos"],
            run["today"],
            datetime.now(),
            shelf=frozenset(run.get("shelf") or ()),
            descriptions={p: parts[p].description for p in set(run["open_pos"]["part"]) if p in parts},
        )
        snap["audit"] = _iso_deep(audit)
        write_audit_state(state)
    except Exception as exc:  # noqa: BLE001 -- the plan still publishes
        snap["audit"] = {"error": str(exc)[:300], "counts": {}, "findings": [], "trend": []}


def load_previous(today_iso):
    """The most recent history snapshot from before today, or None."""
    hist = os.path.join(DATA_DIR, "history")
    try:
        days = sorted(f[:-5] for f in os.listdir(hist) if f.endswith(".json"))
    except OSError:
        return None
    earlier = [d for d in days if d < today_iso]
    if not earlier:
        return None
    try:
        with open(os.path.join(hist, earlier[-1] + ".json"), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def progress(latest, previous):
    """What changed since the previous run -- the 'feel it' numbers."""
    if not latest or not previous:
        return None
    now = {b["part"] for b in latest["buys"]}
    before = {b["part"]: b for b in previous["buys"]}
    cleared = [before[p] for p in before if p not in now]
    cleared.sort(key=lambda b: -b.get("order_value", 0))
    return {
        "since": previous["today"],
        "cleared": len(cleared),
        "cleared_value": round(sum(b.get("order_value", 0) for b in cleared), 2),
        "cleared_parts": [b["part"] for b in cleared[:8]],
        "new": len(now - set(before)),
    }


# ── Promise check data ──────────────────────────────────────────────────
# Firm supply timelines, the BOM, part basics and lead times: everything
# core/atp.py needs, so the Promise page answers in milliseconds without MAX.


def build_atp(run):
    from .core.atp import timelines

    lead = run["lead_times"]
    parts = run["parts"]
    return {
        "today": run["today"].isoformat(),
        "timelines": {
            p: [start, [[_iso(d), q] for d, q in ev]]
            for p, (start, ev) in timelines(run["result"].ledger).items()
        },
        "children": run["children"],
        "parts": {
            p: [v.type, v.description, v.mfg_lt, v.purchase_lt, v.unit_cost]
            for p, v in parts.items()
            if v.type in ("A", "B")
        },
        "lead": {p: s["median"] for p, s in lead.items()},
    }


def write_atp(data):
    os.makedirs(DATA_DIR, exist_ok=True)
    path = os.path.join(DATA_DIR, "atp.json")
    fd, tmp = tempfile.mkstemp(dir=DATA_DIR, prefix=".atp-")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh, separators=(",", ":"), default=str)
    os.replace(tmp, path)


_atp_cache = {"mtime": None, "data": None}


def load_atp():
    """The promise-check data, re-read only when the file changes."""
    path = os.path.join(DATA_DIR, "atp.json")
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return None
    if _atp_cache["mtime"] != mtime:
        with open(path, encoding="utf-8") as fh:
            _atp_cache.update(mtime=mtime, data=json.load(fh))
    return _atp_cache["data"]
