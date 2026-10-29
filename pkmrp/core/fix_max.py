"""Fix in MAX: records that still name a part Engineering obsoleted.

When an ECN obsoletes a part (its latest closed ECN sets rev ZZ in Ron's ECN
app), the planning bills get switched, but anything entered earlier keeps
naming the old part -- and MRP keeps planning it (46 orders on the obsolete
station interface 00-2930-00G had MRP buying a dead support bracket). This
finds every such record, each plan, so they get fixed instead of found by
accident:

  * open customer-order lines naming an obsolete part;
  * open master-schedule (forecast) entries still carrying one;
  * released work orders with an obsolete component on their pick list;
  * live BOMs (a parent with demand) still using one -- an ECN fix;
  * coming soon: order lines on a part an open ECN will obsolete.

Each row carries the part the same ECN released in its place, when one can
be told (same base part number, released on that ECN), and any replacement
rule a planner set in PK-MRP. Rows leave the list by themselves once MAX is
corrected. Pure.
"""

from collections import defaultdict
from datetime import date

UNSCHEDULED_YEAR = 2030  # SO lines parked on 2030+ dates are unscheduled
# Drawings and documents (90- documents, 97- docs/drawings): an obsoleted
# drawing on a BOM buys nothing, so it stays off the BOM list.
DOC_PREFIXES = ("90-", "97-")


def _day(v):
    return v.date().isoformat() if v is not None and v == v else None


def obsolete_map(ecn_rows):
    """({part: closed ECN that obsoleted it}, {part: [open ECNs that will]})."""
    done, coming = {}, defaultdict(list)
    for r in ecn_rows.itertuples(index=False):
        part = (r.part or "").strip().upper()
        info = {"ecn": r.ecn, "status": r.status, "originator": r.originator,
                "closed": _day(r.closed), "change": (r.change or "").strip()}
        if r.status == "Closed":
            done[part] = info
        elif (r.new_rev or "").upper() == "ZZ":
            coming[part].append(info)
    return done, dict(coming)


def suggestions(releases, parts):
    """{obsolete: [released parts that exist in MAX]} from ECN release pairs."""
    out = defaultdict(list)
    for r in releases.itertuples(index=False):
        new = (r.released or "").strip().upper()
        if new in parts and new not in out[r.obsolete.upper()]:
            out[r.obsolete.upper()].append(new)
    return {k: sorted(v) for k, v in out.items()}


def worklist(ecn_rows, releases, so_df, wo_req_df, ms_req_df, children, demanded, parts,
             rules, today):
    """Everything in MAX still naming an obsolete part, grouped by what to fix."""
    done, coming = obsolete_map(ecn_rows)
    suggest = suggestions(releases, parts)

    def fix(part):
        rule = (rules or {}).get(part)
        return {
            "ecn": done[part],
            "suggest": suggest.get(part, []),
            "planned_as": rule["part"] if rule else None,
            "description": parts[part].description if part in parts else "",
        }

    so_lines, soon = [], []
    for r in so_df.itertuples(index=False):
        part = (r.part or "").upper()
        due = r.cur_due.date() if r.cur_due == r.cur_due else None
        row = {
            "so": r.so, "line": r.line, "delivery": r.delivery, "part": part,
            "customer": r.customer or r.customer_id, "qty": float(r.qty_due),
            "due": due.isoformat() if due else None,
            "unscheduled": bool(due and due.year >= UNSCHEDULED_YEAR),
        }
        if part in done:
            so_lines.append({**row, **fix(part)})
        elif part in coming:
            soon.append({**row, "description": parts[part].description if part in parts else "",
                         "coming": coming[part]})

    ms_entries = [
        {"ms": r.ms, "req_order": r.req_order, "line": r.line, "delivery": r.delivery,
         "planning_bill": r.parent, "reference": r.reference, "part": r.part.upper(),
         "qty": float(r.qty_open), "due": _day(r.due), **fix(r.part.upper())}
        for r in ms_req_df.itertuples(index=False)
        if (r.part or "").upper() in done
    ]
    work_orders = [
        {"wo": r.wo, "builds": r.parent, "part": r.part.upper(), "qty": float(r.qty_open),
         "due": _day(r.due), **fix(r.part.upper())}
        for r in wo_req_df.itertuples(index=False)
        if (r.part or "").upper() in done
    ]
    boms = [
        {"parent": parent, "part": comp.upper(), "qty_per": qty,
         "parent_description": parts[parent].description if parent in parts else "", **fix(comp.upper())}
        for parent, kids in children.items()
        if parent in demanded and parent.upper() not in done
        for comp, qty in kids
        if comp.upper() in done and not comp.upper().startswith(DOC_PREFIXES)
    ]

    for rows, key in ((so_lines, "due"), (ms_entries, "due"), (work_orders, "due"), (soon, "due")):
        rows.sort(key=lambda r: (r[key] or "9999", r["part"]))
    boms.sort(key=lambda r: (r["part"], r["parent"]))
    sched = [r for r in so_lines if not r["unscheduled"]]
    return {
        "status": "ok",
        "so_lines": so_lines,
        "ms_entries": ms_entries,
        "work_orders": work_orders,
        "boms": boms,
        "coming": soon,
        "counts": {
            "so_lines": len(so_lines),
            "so_orders": len({r["so"] for r in so_lines}),
            "so_scheduled": len(sched),
            "so_parts": len({r["part"] for r in so_lines}),
            "ms_entries": len(ms_entries),
            "work_orders": len({r["wo"] for r in work_orders}),
            "boms": len(boms),
            "coming": len(soon),
        },
        "as_of": today.isoformat() if isinstance(today, date) else today,
    }


def bulk_rows(fix):
    """Rows for the bulk-change CSV (the shape Tim works from): one per record."""
    out = []
    for r in fix.get("so_lines", []):
        out.append(["SO line", r["so"], r["line"], r["delivery"], r["part"],
                    r["planned_as"] or ("|".join(r["suggest"])), r["qty"], r["due"] or "",
                    r["customer"], r["ecn"]["ecn"]])
    for r in fix.get("ms_entries", []):
        out.append(["MS entry", r["req_order"], r["line"], r["delivery"], r["part"],
                    r["planned_as"] or ("|".join(r["suggest"])), r["qty"], r["due"] or "",
                    r["planning_bill"], r["ecn"]["ecn"]])
    for r in fix.get("work_orders", []):
        out.append(["Work order", r["wo"], "", "", r["part"],
                    r["planned_as"] or ("|".join(r["suggest"])), r["qty"], r["due"] or "",
                    r["builds"], r["ecn"]["ecn"]])
    return out
