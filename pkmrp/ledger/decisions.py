"""Write each planning run's recommendations to the Decision Ledger.

Shadow mode is only worth running if, weeks later, we can put what PK-MRP
said beside what people did and what it cost. So every run:

  1. records itself (mrp_run) with a hash of its inputs;
  2. turns the plan into recommendations -- every buy to place within the
     horizon, every expedite / push-out / cancel / beyond-backlog on an open
     PO line -- each with a content hash and its why;
  3. inserts only the ones not already open (an unchanged recommendation
     repeated hourly is one row, not 24 a day);
  4. closes open ones this run no longer makes ("no longer recommended").

Pure functions build the rows; record() is the only I/O.
"""

import hashlib
import json
import socket
from datetime import date, datetime

LEDGER_KINDS = {
    "expedite_open_po": "expedite",
    "push_out_open_po": "push_out",
    "cancel_candidate": "cancel",
    "beyond_backlog": "beyond_backlog",
}


def _h(*parts):
    return hashlib.sha256("|".join("" if p is None else str(p) for p in parts).encode()).hexdigest()


def inputs_hash(run):
    """A fingerprint of what the plan was computed from: the open backlog
    lines, open receipts, nettable stock and the settings."""
    so = run["so_lines"]
    so_part = sorted(
        zip(
            so["so"],
            so["line"],
            so["part"],
            so["qty_due"].round(4),
            so["cus_due"].astype(str),
            strict=True,
        )
    )
    rec = sorted((r.ref, r.part, round(r.qty, 4), str(r.date)) for r in run["receipts"])
    stock = sorted((p, round(q, 4)) for p, q in run["stock"].items())
    return _h(json.dumps([so_part, rec, stock, repr(run["settings"])], default=str))


def recommendations(run, snap, mode_of=lambda segment: "shadow"):
    """[row dict] for mrp_recommendation, before run_id / created_at."""
    seg = {r["part"]: r["segment"] for r in run.get("segments", [])}
    out = []
    for b in snap["buys"]:
        why = {
            "sales_orders": b.get("sales_orders", [])[:40],
            "order_values": {
                so: (snap.get("so_values") or {}).get(so, 0.0)
                for so in b.get("sales_orders", [])[:40]
            },
            "for_parts": b.get("for_parts", [])[:20],
            "pegs": [p["ref"] for p in b.get("pegs", [])][:40],
            "vendor": b.get("vendor"),
            "planned_lines": b.get("planned_lines"),
        }
        segment = seg.get(b["part"], "")
        out.append(
            {
                "kind": "buy",
                "part": b["part"],
                "ref": None,
                "qty": float(b["qty"]),
                "need_by": date.fromisoformat(b["need_by"]),
                "place_by": date.fromisoformat(b["place_by"]),
                "lead_days": float(b["lead_days"]),
                "lead_source": b["lead_source"][:48],
                "segment": segment,
                "mode": mode_of(segment),
                "order_count": b["orders"],
                "order_value": float(b["order_value"]),
                "why_json": json.dumps(why),
                "content_hash": _h(
                    "buy", b["part"], round(float(b["qty"]), 4), b["need_by"], b["place_by"]
                ),
            }
        )
    for e in run["result"].exceptions:
        kind = LEDGER_KINDS.get(e.kind)
        if not kind:
            continue
        segment = seg.get(e.part, "")
        why = {"detail": e.detail, "days": e.days, "pegs": [p.ref for p in e.pegs][:40]}
        out.append(
            {
                "kind": kind,
                "part": e.part,
                "ref": e.ref[:48],
                "qty": float(e.qty or 0),
                "need_by": None,
                "place_by": None,
                "lead_days": None,
                "lead_source": None,
                "segment": segment,
                "mode": mode_of(segment),
                "order_count": None,
                "order_value": None,
                "why_json": json.dumps(why),
                "content_hash": _h(kind, e.part, e.ref, round(float(e.qty or 0), 4), e.days),
            }
        )
    return out


def record(engine, run, snap, version="", now=None):
    """Write one run to the ledger. Returns {'run_id', 'new', 'closed', 'open'}."""
    from sqlalchemy import and_, insert, select, update

    from ..db.store import recommendation
    from ..db.store import run as run_t

    now = now or datetime.now()
    rows = recommendations(run, snap)
    current = {r["content_hash"] for r in rows}
    with engine.begin() as conn:
        run_id = conn.execute(
            insert(run_t).values(
                plan_date=run["today"],
                started_at=now,
                finished_at=datetime.now(),
                host=socket.gethostname()[:64],
                app_version=version[:32],
                inputs_hash=inputs_hash(run),
                inputs_json=json.dumps(
                    {"counts": run["counts"], "timings": run["timings"]}, default=str
                ),
                status="ok",
            )
        ).inserted_primary_key[0]
        open_rows = conn.execute(
            select(recommendation.c.rec_id, recommendation.c.content_hash).where(
                recommendation.c.closed_run_id.is_(None)
            )
        ).all()
        open_hashes = {h for _, h in open_rows}
        new = [
            dict(r, run_id=run_id, created_at=now)
            for r in rows
            if r["content_hash"] not in open_hashes
        ]
        if new:
            conn.execute(insert(recommendation), new)
        stale = [rid for rid, h in open_rows if h not in current]
        for i in range(0, len(stale), 500):
            conn.execute(
                update(recommendation)
                .where(
                    and_(
                        recommendation.c.rec_id.in_(stale[i : i + 500]),
                        recommendation.c.closed_run_id.is_(None),
                    )
                )
                .values(closed_run_id=run_id, closed_at=now, closed_reason="no longer recommended")
            )
        moved = _segment_changes(conn, run)
    return {
        "run_id": run_id,
        "new": len(new),
        "closed": len(stale),
        "open": len(open_hashes) - len(stale) + len(new),
        "segments_changed": moved,
    }


def _segment_changes(conn, run):
    """Append a mrp_segment_history row for each part whose segment differs
    from its latest recorded one -- the history of reclassifications, not a
    daily copy. Returns how many changed."""
    from sqlalchemy import func, insert, select

    from ..db.store import segment_history as sh

    latest_day = (
        select(sh.c.part, func.max(sh.c.effective_date).label("d")).group_by(sh.c.part).subquery()
    )
    known = dict(
        conn.execute(
            select(sh.c.part, sh.c.segment).join(
                latest_day,
                (sh.c.part == latest_day.c.part) & (sh.c.effective_date == latest_day.c.d),
            )
        ).all()
    )
    rows = [
        {
            "effective_date": run["today"],
            "part": r["part"],
            "segment": r["segment"],
            "p50_days": r.get("p50_days"),
            "p80_days": r.get("p80_days"),
            "reasons": json.dumps(r.get("reasons", [])),
        }
        for r in run.get("segments", [])
        if known.get(r["part"]) != r["segment"]
    ]
    if rows:
        conn.execute(insert(sh), rows)
    return len(rows)
