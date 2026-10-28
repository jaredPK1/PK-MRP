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

from .core.calendar import plus_workdays
from .core.overbuy import overbuys
from .core.params import purlt_proposals
from .core.rank import buy_list
from .core.story import build_story

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
    horizon = plus_workdays(today, 5)  # rank.buy_list's horizon
    for b in buys:
        part = b["part"]
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
                later_buys=[
                    (o.place_by, o.qty)
                    for o in res.planned
                    if o.part == part and o.kind == "buy" and o.place_by > horizon
                ],
            )
        )
        b["late_lines"] = late_by_part.get(part, 0)
        b["pegs"] = [
            {"ref": p.ref}
            for o in res.planned
            if o.part == part and o.kind == "buy"
            for p in o.pegs
        ][:60]
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
        },
        "buys": [{k: _iso(v) for k, v in b.items()} for b in buys],
        "segments": [r for r in segments if r["segment"] != "order_driven"],
        "segment_counts": dict(seg_counts),
        "params": params,
        "committed_plans": [_iso_deep(cp) for cp in run.get("committed_plans", [])],
        "pipeline": _iso_deep(run.get("pipeline") or {"status": "off"}),
        "overbuys": _iso_deep(
            overbuys(
                res.exceptions,
                run["open_pos"],
                res.demands,
                run["stock"],
                run["parts"],
                run.get("segments", []),
                run.get("vendor_name") or {},
                today,
            )
        ),
    }


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


def load_latest():
    try:
        with open(os.path.join(DATA_DIR, "latest.json"), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


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
            p: [v.type, v.description, v.mfg_lt, v.purchase_lt]
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
