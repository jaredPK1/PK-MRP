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

from .core.params import purlt_proposals
from .core.rank import buy_list

DATA_DIR = os.environ.get("DATA_DIR", os.path.join(os.getcwd(), "data"))
WHY_DETAIL_FOR = 60  # full why trace kept for the top N buys


def _iso(v):
    return v.isoformat() if isinstance(v, (date, datetime)) else v


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
    for b in buys[:WHY_DETAIL_FOR]:
        part = b["part"]
        b["ledger"] = [
            {"date": _iso(d), "qty": q, "kind": k, "ref": ref}
            for d, q, k, ref in res.ledger.get(part, [])
        ][:120]
        b["pegs"] = [
            {"ref": p.ref, "path": list(p.path), "value": p.value}
            for o in res.planned
            if o.part == part and o.kind == "buy"
            for p in o.pegs
        ][:60]
        b["exceptions"] = [
            {"kind": e.kind, "ref": e.ref, "detail": e.detail}
            for e in res.exceptions
            if e.part == part
        ][:20]
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
