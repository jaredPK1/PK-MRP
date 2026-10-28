"""Parameter health: proposed PURLT_01 changes, with the evidence for each.

Replaces part-by-part lead-time edits by email. A bought part is listed
when its own receipt history (>= MIN_LINES fully received lines, ordered-
early lines excluded -- see leadtime.py) puts its median more than
`tolerance` away from PURLT_01. The proposal is its P80 (median when it has
fewer than P80_LINES receipts), rounded up to the next 5 business days: MRP
places orders off PURLT, and a setting at the median would be late on 1
order in 2.

A human keys the accepted changes into MAX. PK-MRP never writes them back.
SAFSTK_01 proposals wait for the committed-supply buffer (core/committed.py);
order-driven parts are bought against the backlog and need none.
"""

import math

ROUND_TO = 5
P80_LINES = 5


def purlt_proposals(parts, lead_stats, segments=None, tolerance=0.25, min_lines=3):
    """[{part, current, proposed, change, direction, ...}], biggest change first."""
    seg = {r["part"]: r["segment"] for r in (segments or [])}
    out = []
    for part, s in lead_stats.items():
        info = parts.get(part)
        cur = float(s.get("purlt") or 0)
        if not info or cur <= 0 or s["lines"] < min_lines or not s["source"].startswith("realized"):
            continue
        if abs(s["median"] / cur - 1) <= tolerance:
            continue
        # P80 needs enough lines to mean something: on 3 receipts one slow PO
        # *is* the P80 (62-0148-02G: median 54, P80 214). Below P80_LINES the
        # proposal is the median.
        basis = s["p80"] if s["lines"] >= P80_LINES else s["median"]
        proposed = max(ROUND_TO, math.ceil(basis / ROUND_TO) * ROUND_TO)
        if proposed == cur:
            continue
        out.append(
            {
                "part": part,
                "description": info.description,
                "buyer": info.buyer,
                "vendor": s.get("vendor") or "",
                "current_bdays": cur,
                "median_bdays": round(s["median"], 1),
                "p80_bdays": round(s["p80"], 1),
                "lines": s["lines"],
                "early_lines": s.get("early_lines", 0),
                "proposed_bdays": proposed,
                "change": round(proposed - cur),
                "direction": "longer" if proposed > cur else "shorter",
                "segment": seg.get(part, ""),
                "basis": "P80" if s["lines"] >= P80_LINES else "median",
            }
        )
    out.sort(key=lambda r: (-abs(r["change"]), r["part"]))
    return out


CSV_COLUMNS = (
    "part",
    "description",
    "buyer",
    "vendor",
    "current_bdays",
    "proposed_bdays",
    "change",
    "direction",
    "median_bdays",
    "p80_bdays",
    "lines",
    "early_lines",
    "basis",
    "segment",
)
