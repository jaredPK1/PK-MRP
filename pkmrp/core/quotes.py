"""Vendor quotes with quantity breaks, kept in quotes.json beside this file.

Part_Vendor holds three breaks per part-vendor and is kept unevenly, so the
sizer only trusts its rows when they look like per-each pricing near the
part's cost. A machine shop's quote breaks that test on purpose: one piece
is several times the lot price (Duyck 261109.02: 62-1132-01G $714.32 for 1,
$113.29 each for 10). A quote entered here is trusted as written for
`use_days` after its date, then dropped -- a stale quote is worse than none.
Pure apart from reading the file.
"""

import json
import os
from datetime import date, timedelta

PATH = os.path.join(os.path.dirname(__file__), "quotes.json")


def current_quotes(today, data=None):
    """{part: {"vendor", "quote", "date", "breaks": [[qty, price]]}}, newest
    current quote per part."""
    if data is None:
        try:
            with open(PATH, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return {}
    out = {}
    for q in sorted(data.get("quotes") or [], key=lambda q: q.get("date") or ""):
        try:
            when = date.fromisoformat(q["date"])
        except (KeyError, TypeError, ValueError):
            continue
        if today > when + timedelta(days=int(q.get("use_days") or 90)):
            continue
        for part, brs in (q.get("parts") or {}).items():
            out[part] = {
                "vendor": q.get("vendor") or "",
                "quote": q.get("quote") or "",
                "date": when,
                "breaks": [[float(a), float(b)] for a, b in brs],
            }
    return out
