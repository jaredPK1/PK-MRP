"""Find a part the way people ask for it: by number or by what it is.

"46-0020", "46002001G", "relay lens", "2300 z stage", "fpga" all work.
A query is split into words; every word has to match the part number or the
description (in any order, either case, singular or plural). Dashes and
spaces in part numbers don't matter, and MAX's abbreviations are understood
-- "assembly" finds ASSY, "board" finds ECB and PCB.

Ranking: the exact part number, then a part-number prefix, then the number
containing it, then a description match -- with parts that have demand or
stock ahead of dead ones, and buy/make parts ahead of other types.
"""

import re

# word -> what MAX writes instead (descriptions are terse, all caps)
ALIASES = {
    "assembly": ("assy", "asy"),
    "assemblies": ("assy", "asy"),
    "board": ("ecb", "pcb", "pcba"),
    "cable": ("cbl", "cable"),
    "connector": ("conn",),
    "option": ("opt", "option"),
    "kit": ("kit",),
    "screw": ("scr", "screw"),
    "washer": ("wshr", "washer"),
    "power": ("pwr", "power"),
    "supply": ("supply", "sply"),
    "motor": ("mtr", "motor"),
    "drawing": ("dwg",),
    "resistor": ("res",),
    "capacitor": ("cap",),
}

_SPLIT = re.compile(r"[\s,;/]+")


def squash(s):
    """Lower case, no dashes, dots or spaces: '46-0020-01G' -> '46002001g'."""
    return re.sub(r"[\s\-_.]", "", (s or "").lower())


def _forms(word):
    w = word.lower()
    out = {w}
    if len(w) > 3 and w.endswith("s"):
        out.add(w[:-1])
    for k in list(out):
        out.update(ALIASES.get(k, ()))
    return out


def score(part, description, query, active=False, part_type=""):
    """A rank for one part, or 0 if it doesn't match."""
    q = (query or "").strip()
    if not q:
        return 0
    pn, qn = squash(part), squash(q)
    if pn == qn:
        base = 1000
    elif qn and pn.startswith(qn):
        base = 600 - min(len(pn) - len(qn), 50)
    elif len(qn) >= 3 and qn in pn:
        base = 400
    else:
        desc = (description or "").lower()
        words = [w for w in _SPLIT.split(q) if w]
        hits = 0
        for w in words:
            forms = _forms(w)
            if any(f in desc for f in forms) or (len(squash(w)) >= 3 and squash(w) in pn):
                hits += 1
            else:
                return 0
        # every word matched; whole-word matches read better than fragments
        whole = sum(1 for w in words if re.search(r"\b" + re.escape(w.lower()), desc))
        base = 100 + 10 * whole + hits
    if active:
        base += 40
    if part_type in ("A", "B"):
        base += 5
    return base


def find(query, catalogue, limit=12):
    """[(part, description, type, active)] best first. `catalogue` is an
    iterable of (part, description, type, active)."""
    scored = []
    for part, desc, ptype, active in catalogue:
        s = score(part, desc, query, active, ptype)
        if s:
            scored.append((-s, part, desc, ptype, active))
    scored.sort()
    return [(p, d, t, a) for _, p, d, t, a in scored[:limit]]
