"""Which MAX part is a Book/Bill 2.0 SKU? Proposals for a person to confirm.

Sales calls things by model and option names -- "2300AG-B", "2302-TCL",
"FK11-SAE-U" -- and only one of its ~200 SKUs is a MAX part number. Two
kinds of evidence say which part a SKU means:

  * name   -- the part number carries it as a segment (01-1050C-03G for
              "1050C System"), or the MAX description names it ("FK11-SAE-U
              CLEAVER", "OPTION, 2302-TCL THIN COATING"). A key dozens of
              descriptions name counts for less. A catch-all "2304 Option"
              names no part at all: the booking's line text says which.
  * orders -- bookings that became SOs: the part was on the orders that had
              the SKU ("together"), and rarely on orders that didn't. Parts
              that ship together (system, accessories, options) tie on this
              alone, which is why it is evidence, not an answer.

Ranked by name + orders, then by the part PK sold most recently (so the
current revision beats one retired years ago). Nothing here is applied:
a confirmed choice goes in mrp_settings 'pipeline_sku_map' from the
Pipeline page, and only then does the SKU become demand.
"""

import re
from collections import defaultdict
from datetime import date

from .search import squash

_SUFFIX = re.compile(r"\s+(option|options|system|systems)$", re.I)
VAGUE = 12  # a name key matching more parts than this is not evidence
SHOW = 3


def is_catch_all(sku):
    """'2304 Option' is a bucket for any 2304 option -- the booking's line
    text says which -- so it is no one part."""
    return bool(re.search(r"\s+options?$", (sku or "").strip(), re.I))


def key_of(sku):
    """'2311 System' -> '2311', '2302-TCL' -> '2302-TCL' (upper case)."""
    return _SUFFIX.sub("", (sku or "").strip()).upper()


def index(catalogue):
    """Make/buy parts (A/B) prepared for name_hits: only they become demand.
    `catalogue` is {part: (type, description)}."""
    return [
        (p, (desc or "").upper(), squash(p))
        for p, (t, desc) in catalogue.items()
        if t in ("A", "B")
    ]


def name_hits(sku, idx):
    """{part: "number" | "description"}: the part number is the SKU (dashes
    aside) or carries it as a segment, or the description names it."""
    key = key_of(sku)
    if len(key) < 3:
        return {}
    word = re.compile(r"(?<![A-Z0-9])" + re.escape(key) + r"(?![A-Z0-9])")
    flat, seg = squash(key), "-" + key + "-"
    hits = {}
    for p, desc, sq in idx:
        if sq == flat or seg in "-" + p.upper() + "-":
            hits[p] = "number"
        elif key in desc and word.search(desc):
            hits[p] = "description"
    return hits


def _orders(booked, so_lines):
    """({sku: {so: qty}}, {part: {so: qty}}) from the two frames."""
    by_sku = defaultdict(lambda: defaultdict(float))
    for r in booked.itertuples(index=False):
        if r.sku and r.so:
            by_sku[r.sku][r.so] += float(r.qty or 0)
    by_part = defaultdict(lambda: defaultdict(float))
    for r in so_lines.itertuples(index=False):
        if r.part and r.so:
            by_part[r.part][r.so] += float(r.qty or 0)
    return by_sku, by_part


def _qty_per(sku_on, part_on, shared):
    """Median MAX qty per sales qty on the orders they share; 1 if unclear."""
    ratios = sorted(part_on[s] / sku_on[s] for s in shared if sku_on[s] > 0 and part_on[s] > 0)
    if not ratios:
        return 1.0
    mid = ratios[len(ratios) // 2]
    return float(round(mid)) if abs(mid - round(mid)) < 0.15 and round(mid) >= 1 else round(mid, 2)


def _when(d):
    return d.strftime("%b %Y") if d else None


def propose(skus, booked, so_lines, catalogue, last_sold, today=None):
    """{sku: {"confidence": strong|likely|weak|none, "orders": n, "candidates": [...]}}

    `catalogue` {part: (type, description)}; only make/buy parts are
    candidates. `last_sold` {part: date}.
    """
    today = today or date.today()
    by_sku, by_part = _orders(booked, so_lines)
    idx = index(catalogue)
    out = {}
    for sku in skus:
        sku_on = by_sku.get(sku, {})
        catch_all = is_catch_all(sku)
        names = {} if catch_all else name_hits(sku, idx)
        vague = sum(1 for k in names.values() if k == "description") > VAGUE
        weight = {"number": 2.5, "description": 1.0 if vague else 2.0}
        named = {p for p, k in names.items() if k == "number" or not vague}
        pool = set(names)
        for p, on in by_part.items():
            if p in catalogue and catalogue[p][0] in ("A", "B") and set(on) & set(sku_on):
                pool.add(p)
        cands = []
        for p in pool:
            shared = set(by_part.get(p, {})) & set(sku_on)
            n = len(shared)
            cover = n / len(sku_on) if sku_on else 0.0
            spec = n / len(by_part[p]) if n else 0.0
            sold = last_sold.get(p)
            age = (today - sold).days / 365.25 if sold else None
            recent = 0.0 if age is None else (0.5 if age <= 1 else 0.3 if age <= 3 else 0.0)
            kind = names.get(p)
            score = weight.get(kind, 0.0) + 2.0 * cover * spec + recent
            evidence = []
            if kind == "number":
                evidence.append(f"its part number carries {key_of(sku)}")
            elif kind:
                evidence.append(f"its description names {key_of(sku)}")
            if n:
                alone = " (and almost never without it)" if spec >= 0.8 else ""
                evidence.append(f"on {n} of {len(sku_on)} orders that had {sku}{alone}")
            evidence.append(f"last sold {_when(sold)}" if sold else "never on a customer order")
            cands.append(
                {
                    "part": p,
                    "description": catalogue[p][1],
                    "type": catalogue[p][0],
                    "score": round(score, 3),
                    "named": p in named,
                    "together": n,
                    "sku_orders": len(sku_on),
                    "part_orders": len(by_part.get(p, {})),
                    "last_sold": sold.isoformat() if sold else None,
                    "qty_per": _qty_per(sku_on, by_part[p], shared) if n else 1.0,
                    "evidence": evidence,
                }
            )
        # among equal scores, the most recently sold first
        cands.sort(key=lambda c: (-c["score"], -_ordinal(c["last_sold"]), c["part"]))
        top = cands[:SHOW]
        out[sku] = {
            "confidence": "weak" if catch_all and top else _confidence(top, named),
            "catch_all": catch_all,
            "orders": len(sku_on),
            "vague_name": vague,
            "candidates": top,
        }
    return out


def _ordinal(iso):
    return date.fromisoformat(iso).toordinal() if iso else 0


def _confidence(top, named):
    if not top:
        return "none"
    c = top[0]
    runner = top[1]["score"] if len(top) > 1 else 0.0
    clear = c["score"] - runner >= 0.5
    if c["named"] and c["together"] >= 2 and c["together"] / max(c["sku_orders"], 1) >= 0.5:
        return "strong"
    if c["together"] >= 3 and c["together"] == c["sku_orders"] == c["part_orders"]:
        return "strong"
    if c["named"] and (len(named) == 1 or clear) and c["last_sold"]:
        return "likely"
    if c["named"] or (c["together"] >= 2 and clear):
        return "likely" if clear else "weak"
    return "weak"
