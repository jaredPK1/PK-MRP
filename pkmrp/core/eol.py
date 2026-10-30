"""EOL watch: parts a maker is ending, and what PK should buy before it goes.

Signals, from integrations/research.py's caches:

  distributor  DigiKey / Mouser / Octopart say the part is NRND, last-time
               buy or obsolete;
  email        a PCN / EOL / last-time-buy notice in the purchasing mailbox;
  news         a notice the weekly web search found on the maker's site.

Each signal's part numbers are matched to PK parts through MAX's MPN file
and vendor part numbers. Per PK part: where it's used (the systems booked
orders put it in), booked demand, stock and open POs, months of cover, and
a last-time-buy quantity -- booked demand plus `ltb_years` of the yearly
rate, less what's on hand and on order.

Pure: plain data in, a JSON-ready dict out.
"""

import re
from collections import defaultdict
from datetime import date, timedelta

BAD = ("obsolete", "last_time_buy", "eol", "nrnd")
RANK = {"obsolete": 0, "eol": 0, "last_time_buy": 1, "nrnd": 2, "pcn": 3, "price": 4, "other": 5}


def norm(pn):
    return re.sub(r"[^A-Z0-9]", "", (pn or "").upper())


def mpn_index(mpn_rows, part_numbers):
    """{normalised number: {PK part}} from MPNs, vendor SKUs and PK's own numbers."""
    idx = defaultdict(set)
    for part, mpn in mpn_rows:
        n = norm(mpn)
        if len(n) >= 4:
            idx[n].add(part)
    for p in part_numbers:
        idx[norm(p)].add(p)
    return idx


def match(numbers, idx):
    out = set()
    for pn in numbers or ():
        out |= idx.get(norm(pn), set())
    return out


def _date(s):
    try:
        return date.fromisoformat(str(s)[:10]) if s else None
    except ValueError:
        return None


def build(
    dist_cache,
    notices,
    news,
    mpn_rows,
    parts,
    demands,
    stock,
    on_order,
    annual,
    today,
    ltb_years=2.0,
):
    """dist_cache {part: {checked, offers:[...]}}; notices [{id, received, subject, sender,
    web_link, notice{...}}]; news [{maker, found_at, notices:[...]}]; mpn_rows [(part, mpn)];
    parts {part: Part}; demands {part: [Demand]}; stock/on_order/annual {part: qty}."""
    idx = mpn_index(mpn_rows, parts)
    signals = defaultdict(list)

    for part, c in (dist_cache or {}).items():
        for o in c.get("offers") or []:
            if o.get("lifecycle") in BAD:
                signals[part].append(
                    {
                        "kind": o["lifecycle"],
                        "source": "distributor",
                        "where": o.get("source", ""),
                        "date": c.get("checked"),
                        "detail": f"{o.get('source', '')}: {o.get('lifecycle_text') or o['lifecycle']} ({o.get('mpn', '')})",
                        "link": o.get("url", ""),
                        "last_order": "",
                        "replacements": [],
                    }
                )
                break
    for m in notices or []:
        n = m.get("notice") or {}
        if not n.get("is_notice"):
            continue
        for part in match(n.get("part_numbers"), idx):
            signals[part].append(
                {
                    "kind": n.get("kind", "other"),
                    "source": "email",
                    "where": m.get("sender", ""),
                    "date": (m.get("received") or "")[:10],
                    "detail": n.get("summary") or m.get("subject", ""),
                    "subject": m.get("subject", ""),
                    "link": m.get("web_link", ""),
                    "last_order": n.get("last_order_date", ""),
                    "replacements": n.get("replacements") or [],
                    "id": m.get("id"),
                }
            )
    for batch in news or []:
        for n in batch.get("notices") or []:
            for part in match(n.get("part_numbers"), idx):
                signals[part].append(
                    {
                        "kind": n.get("kind", "other"),
                        "source": "news",
                        "where": batch.get("maker", ""),
                        "date": n.get("published") or (batch.get("found_at") or "")[:10],
                        "detail": n.get("summary", ""),
                        "link": n.get("source_url", ""),
                        "last_order": n.get("last_order_date", ""),
                        "replacements": n.get("replacements") or [],
                    }
                )

    items = []
    year = today + timedelta(days=365)
    for part, sigs in signals.items():
        info = parts.get(part)
        ds = demands.get(part, [])
        booked = sum(d.qty for d in ds)
        booked_12m = sum(d.qty for d in ds if d.date <= year)
        rate = max(annual.get(part, 0.0), booked_12m)
        have = stock.get(part, 0.0) + on_order.get(part, 0.0)
        need = max(booked, booked + rate * ltb_years - booked_12m) if rate else booked
        ltb = max(need - have, 0.0)
        systems, orders = set(), set()
        for d in ds:
            for p in d.pegs:
                systems.add(p.root_part)
                if p.ref.startswith("SO "):
                    orders.add(p.ref[3:].split("/")[0])
        last_orders = [x for x in (_date(s["last_order"]) for s in sigs) if x]
        last_order = min(last_orders) if last_orders else None
        kind = min((s["kind"] for s in sigs), key=lambda k: RANK.get(k, 9))
        unit = float(info.unit_cost) if info else 0.0
        items.append(
            {
                "part": part,
                "description": info.description if info else "",
                "kind": kind,
                "last_order": last_order,
                "days_left": (last_order - today).days if last_order else None,
                "signals": sorted(sigs, key=lambda s: str(s.get("date") or ""), reverse=True),
                "replacements": sorted({r for s in sigs for r in s["replacements"]}),
                "booked": booked,
                "booked_12m": booked_12m,
                "yearly": rate,
                "on_hand": stock.get(part, 0.0),
                "on_order": on_order.get(part, 0.0),
                "cover_months": round(have / (rate / 12), 1) if rate else None,
                "ltb_qty": round(ltb, 2),
                "ltb_cost": round(ltb * unit, 2),
                "systems": sorted(systems)[:10],
                "orders": len(orders),
            }
        )
    items.sort(
        key=lambda i: (
            RANK.get(i["kind"], 9),
            i["days_left"] if i["days_left"] is not None else 9999,
            -i["ltb_cost"],
        )
    )
    return {
        "today": today,
        "items": items,
        "counts": {k: sum(1 for i in items if i["kind"] == k) for k in RANK},
    }
