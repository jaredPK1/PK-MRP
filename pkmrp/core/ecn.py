"""ECNs from Ron's ECN app (pk_ecn), the source of truth for engineering changes.

Two things a buyer needs to know about a part, read fresh each plan:

  * open ECNs on it -- In Process through Implementing: Engineering is
    changing it, so check before buying a lot;
  * obsolete -- the latest closed ECN on the part set its revision to ZZ,
    PK's mark for obsolete. MAX has no usable obsolete flag, so this is the
    only record. A later closed ECN that brings the part back clears it (the
    query keeps only each part's latest closed row).

And one alert: buys of an obsoleted part, with what is pulling the demand,
since that is usually an old parent or an open order still calling it out.

Pure; the rows come from extract.ecn_parts.
"""

OPEN_STAGES = (
    "In Process",
    "Manager's Review",
    "ECN Review",
    "Out for Approval",
    "Approved",
    "Implementing",
)


def _day(v):
    return v.date().isoformat() if v is not None and v == v else None


def by_part(df, keep):
    """{part: {"open": [ecn, ...] newest first, "obsolete": ecn or None}} for
    the parts in `keep` that have either."""
    out = {}
    for r in df.itertuples(index=False):
        part = (r.part or "").strip().upper()
        if part not in keep:
            continue
        ecn = {
            "ecn": r.ecn,
            "status": r.status,
            "originator": r.originator,
            "opened": _day(r.opened),
            "closed": _day(r.closed),
            "old_rev": r.old_rev,
            "new_rev": r.new_rev,
            "change": (r.change or "").strip(),
            "summary": (r.summary or "").strip(),
            "blocker": (r.blocker or "").strip(),
        }
        slot = out.setdefault(part, {"open": [], "obsolete": None})
        if r.status == "Closed":
            slot["obsolete"] = ecn
        else:
            slot["open"].append(ecn)
    for slot in out.values():
        slot["open"].sort(key=lambda e: e["ecn"], reverse=True)
    return out


def obsolete_buys(buys, ecn_parts):
    """Buys of a part an ECN obsoleted: the buy, its ECN, and what pulls the
    demand (each parent, marked when that parent is obsolete too)."""
    rows = []
    for b in buys:
        info = ecn_parts.get(b["part"]) or {}
        if not info.get("obsolete"):
            continue
        story = b.get("story") or {}
        via = [
            {
                "part": g["part"],
                "description": g.get("description", ""),
                "units": g.get("units"),
                "obsolete": bool((ecn_parts.get(g["part"]) or {}).get("obsolete")),
                "open_ecns": [e["ecn"] for e in (ecn_parts.get(g["part"]) or {}).get("open", [])],
            }
            for g in story.get("goes_into") or []
        ]
        rows.append(
            {
                "part": b["part"],
                "description": b.get("description", ""),
                "qty": b.get("qty"),
                "order_value": b.get("order_value", 0),
                "orders": b.get("orders", 0),
                "ecn": info["obsolete"],
                "open_ecns": info.get("open", []),
                "via": via,
            }
        )
    rows.sort(key=lambda r: -(r["order_value"] or 0))
    return rows
