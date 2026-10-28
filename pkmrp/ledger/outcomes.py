"""What people actually did after a recommendation, read from MAX.

The other half of the Decision Ledger. Nobody types outcomes in: each run
compares the ledger's recommendations with the PO history MAX already has.

  buy             -> po_placed     a PO line for the part created on or after
                                   the recommendation (each PO line is matched
                                   to one recommendation, earliest first)
  expedite        -> po_expedited  the PO line's due date is now earlier than
                                   when it was flagged
  push_out        -> po_pushed     ... later than when it was flagged
  cancel          -> po_cancelled  the line closed or was cut without being
                                   received
  any PO-line rec -> received      the line received after the recommendation

Idempotent: an outcome already recorded for (rec, what, ref) is not added
again. match() is pure; record_outcomes() is the I/O.
"""

import json
import re
from datetime import date, datetime, timedelta

from ..core.calendar import as_date, workdays_between

_DUE = re.compile(r"due (\d{4}-\d{2}-\d{2})")
PLACED_GRACE = timedelta(days=1)  # a PO keyed the same morning still counts


def _ref(po, line, delivery):
    return f"PO {po}/{line}/{delivery}"


def _flagged_due(why_json):
    """The PO line's due date when the recommendation was made (from its why)."""
    try:
        detail = json.loads(why_json or "{}").get("detail", "")
    except ValueError:
        return None
    m = _DUE.search(detail or "")
    return date.fromisoformat(m.group(1)) if m else None


def match(recs, po_lines, existing, today):
    """[outcome row] to add.

    recs      [{rec_id, kind, part, ref, qty, place_by, created_at, why_json}]
    po_lines  po_history frame (po, line, delivery, part, status, created,
              cur_due, qty_current, qty_received, last_receipt)
    existing  {(rec_id, what, ref)} already in mrp_outcome
    """
    by_ref, by_part = {}, {}
    for r in po_lines.itertuples(index=False):
        key = _ref(r.po, r.line, r.delivery)
        by_ref[key] = r
        by_part.setdefault(r.part, []).append((as_date(r.created), key, r))
    for lines in by_part.values():
        lines.sort(key=lambda x: (x[0] or date.min, x[1]))

    used = {ref for (_, what, ref) in existing if what == "po_placed"}
    out = []

    def add(rec, what, ref, qty=None, event_date=None, detail=None):
        if (rec["rec_id"], what, ref) in existing:
            return
        existing.add((rec["rec_id"], what, ref))
        out.append(
            {
                "rec_id": rec["rec_id"],
                "observed_at": datetime.combine(today, datetime.min.time()),
                "what": what,
                "part": rec["part"],
                "ref": ref,
                "qty": qty,
                "event_date": event_date,
                "detail": json.dumps(detail or {}),
            }
        )

    for rec in sorted(recs, key=lambda r: (r["created_at"], r["rec_id"])):
        made = as_date(rec["created_at"])
        if rec["kind"] == "buy":
            for created, key, r in by_part.get(rec["part"], ()):
                if created is None or created < made - PLACED_GRACE or key in used:
                    continue
                used.add(key)
                place_by = as_date(rec.get("place_by"))
                late = workdays_between(place_by, created) if place_by else None
                add(
                    rec,
                    "po_placed",
                    key,
                    float(r.qty_current or 0),
                    created,
                    {
                        "recommended_qty": rec.get("qty"),
                        "place_by": str(place_by),
                        "workdays_after_place_by": late,
                    },
                )
                break
            continue

        line = by_ref.get(rec.get("ref") or "")
        if line is None:
            continue
        was = _flagged_due(rec.get("why_json"))
        now_due = as_date(line.cur_due)
        if rec["kind"] == "expedite" and was and now_due and now_due < was:
            add(
                rec,
                "po_expedited",
                rec["ref"],
                None,
                now_due,
                {"was": str(was), "now": str(now_due), "days_pulled_in": (was - now_due).days},
            )
        elif rec["kind"] == "push_out" and was and now_due and now_due > was:
            add(
                rec,
                "po_pushed",
                rec["ref"],
                None,
                now_due,
                {"was": str(was), "now": str(now_due), "days_pushed": (now_due - was).days},
            )
        elif (
            rec["kind"] == "cancel"
            and float(line.qty_received or 0) <= 0
            and (
                str(line.status) == "5" or float(line.qty_current or 0) < float(rec.get("qty") or 0)
            )
        ):
            add(
                rec,
                "po_cancelled",
                rec["ref"],
                float(line.qty_current or 0),
                today,
                {"status": str(line.status), "qty_now": float(line.qty_current or 0)},
            )
        last = as_date(line.last_receipt)
        if last and last >= made and float(line.qty_received or 0) > 0:
            add(rec, "received", rec["ref"], float(line.qty_received), last, {})
    return out


def record_outcomes(engine, po_lines, today, lookback_days=200):
    """Match recommendations made in the last `lookback_days` and insert the
    new outcomes. Returns how many were added."""
    from sqlalchemy import insert, select

    from ..db.store import outcome
    from ..db.store import recommendation as rec_t

    since = datetime.combine(today - timedelta(days=lookback_days), datetime.min.time())
    with engine.begin() as conn:
        recs = [
            dict(r._mapping)
            for r in conn.execute(
                select(
                    rec_t.c.rec_id,
                    rec_t.c.kind,
                    rec_t.c.part,
                    rec_t.c.ref,
                    rec_t.c.qty,
                    rec_t.c.place_by,
                    rec_t.c.created_at,
                    rec_t.c.why_json,
                ).where(rec_t.c.created_at >= since)
            )
        ]
        if not recs:
            return 0
        existing = {
            (r.rec_id, r.what, r.ref)
            for r in conn.execute(
                select(outcome.c.rec_id, outcome.c.what, outcome.c.ref).where(
                    outcome.c.observed_at >= since - timedelta(days=30)
                )
            )
        }
        rows = match(recs, po_lines, existing, today)
        if rows:
            conn.execute(insert(outcome), rows)
    return len(rows)
