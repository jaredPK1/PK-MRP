"""EOL watch: parts a maker is ending, and what PK should buy before it goes.

Signals, from integrations/research.py's caches:

  distributor  DigiKey / Mouser / Octopart say the part is NRND, last-time
               buy or obsolete;
  email        a PCN / EOL / last-time-buy notice in the purchasing mailbox;
  news         a notice the weekly web search found on the maker's site.

Each signal's part numbers are matched to PK parts through MAX's MPN file
and vendor part numbers. A distributor answer counts only when it is the
same part: the same number (or the distributor SKU we asked by) AND, when
MAX names a maker for that number, the same maker -- a distributor search
for "45-803" also returns a Wiha screwdriver, and "5763" an Alpha Wire
cable. A part with another approved maker part number in MAX that is still
active isn't going away: it's a switch, not a last-time buy.

Per PK part: where it's used (the systems booked orders put it in), booked
demand, stock and open POs, months of cover, a last-time-buy quantity --
booked demand plus `ltb_years` of the yearly rate, less what's on hand and
on order -- and a tier:

  act    obsolete / end of life / last-time buy, booked orders need it,
         stock and POs don't cover them, and no approved alternate is active;
  watch  used, but covered, an approved alternate is active, or a softer
         notice (not for new designs, change notice);
  fyi    nothing booked needs it.

Pure: plain data in, a JSON-ready dict out.
"""

import re
from collections import defaultdict
from datetime import date, timedelta

BAD = ("obsolete", "last_time_buy", "eol", "nrnd")
RANK = {"obsolete": 0, "eol": 0, "last_time_buy": 1, "nrnd": 2, "pcn": 3, "price": 4, "other": 5}


def norm(pn):
    return re.sub(r"[^A-Z0-9]", "", (pn or "").upper())


TIERS = ("act", "watch", "fyi")
# Words that don't tell two makers apart ("Texas Instruments Inc" vs "TI").
MAKER_NOISE = {
    "inc", "corp", "corporation", "co", "company", "ltd", "llc", "gmbh", "ag", "sa", "the",
    "electronics", "electronic", "semiconductor", "semiconductors", "semi", "technologies",
    "technology", "tech", "devices", "components", "solutions", "division", "international",
    "group", "usa", "america", "products", "industries", "systems", "and", "of", "formerly",
    "specialty", "connectivity", "labs", "lab", "design", "designs", "power", "thermal",
    "optics", "optical", "instruments", "manufacturing", "mfg", "precision", "industrial",
    "engineering", "wire", "cable", "electric",
}
# Same maker under another name (renames, acquisitions, short forms).
MAKER_ALIASES = {
    "ti": "texas", "onsemi": "on", "fairchild": "on", "cui": "samesky", "same": "samesky",
    "sky": "samesky", "tark": "laird", "fci": "amphenol", "zetex": "diodes", "linear": "analog",
    "maxim": "analog", "adi": "analog", "atmel": "microchip", "microsemi": "microchip",
    "freescale": "nxp", "intersil": "renesas", "idt": "renesas", "avago": "broadcom",
    "kyocera": "avx", "sl": "advanced", "te": "tyco", "3m": "3m",
}


def _maker_words(name):
    words = re.findall(r"[a-z0-9]+", (name or "").lower())
    return {MAKER_ALIASES.get(w, w) for w in words if w not in MAKER_NOISE and (len(w) > 1 or w.isdigit())}


def maker_match(a, b):
    """Do two maker names mean the same company? Blank on either side: can't tell -> True."""
    if not (a or "").strip() or not (b or "").strip():
        return True
    wa, wb = _maker_words(a), _maker_words(b)
    if wa & wb:
        return True
    ca, cb = norm(a), norm(b)
    return bool(ca and cb and (ca.startswith(cb) or cb.startswith(ca)))


def mpn_index(mpn_rows, part_numbers):
    """{normalised number: {PK part}} from MPNs, vendor SKUs and PK's own numbers."""
    idx = defaultdict(set)
    for row in mpn_rows:
        n = norm(row[1])
        if len(n) >= 4:
            idx[n].add(row[0])
    for p in part_numbers:
        idx[norm(p)].add(p)
    return idx


def approved_numbers(mpn_rows):
    """{part: {normalised MPN: (MPN as written, maker)}} -- the maker part numbers
    MAX approves for each part (MPN file and approved-vendor MPNs; not vendor
    SKUs). Rows are (part, mpn) or (part, mpn, maker, source)."""
    out = defaultdict(dict)
    for row in mpn_rows:
        part, mpn = row[0], row[1]
        maker = row[2] if len(row) > 2 else ""
        source = row[3] if len(row) > 3 else "mpn_file"
        n = norm(mpn)
        if source == "vendor_sku" or len(n) < 4 or not any(ch.isdigit() for ch in n):
            continue  # "SEE PART NOTES", "BUNTING": words, not part numbers
        if n not in out[part] or (maker and not out[part][n][1]):
            out[part][n] = (mpn.strip(), (maker or "").strip())
    return out


def same_part(offer, asked, known):
    """Is this distributor offer the part we asked about? `asked` is the number
    looked up, `known` the part's approved numbers {norm: (mpn, maker)}."""
    n_asked, n_mpn = norm(asked), norm(offer.get("mpn"))
    if norm(offer.get("sku")) and norm(offer.get("sku")) == n_asked:
        return True  # asked by the distributor's own SKU: one product
    if not n_mpn or (n_mpn != n_asked and n_mpn not in known):
        return False
    maker = (known.get(n_mpn) or known.get(n_asked) or ("", ""))[1]
    if maker:
        return maker_match(offer.get("maker"), maker)
    # no maker on file: a short or all-digit number matches too many things
    return not (n_mpn.isdigit() or len(n_mpn) < 6)


def worst(offers):
    """The most serious lifecycle among offers ('' if none is bad)."""
    bad = [o for o in offers if o.get("lifecycle") in BAD]
    return min(bad, key=lambda o: RANK.get(o["lifecycle"], 9)) if bad else None


def alternates(part, entry, known):
    """Other approved maker numbers for the part and what distributors say
    about each: active | bad | unknown | unchecked."""
    asked = norm(entry.get("mpn"))
    seen_mpns = {norm(o.get("mpn")) for o in entry.get("offers") or []
                 if same_part(o, entry.get("mpn"), known)}
    checked = entry.get("alts") or {}
    out = []
    for n, (mpn, maker) in known.items():
        if n == asked or n in seen_mpns:
            continue
        c = checked.get(mpn)
        if c is None:
            status = "unchecked"
        else:
            ok = [o for o in c.get("offers") or [] if same_part(o, mpn, known)]
            if any(o.get("lifecycle") == "active" for o in ok):
                status = "active"
            elif worst(ok):
                status = "bad"
            else:
                status = "unknown"
        out.append({"mpn": mpn, "maker": maker, "status": status})
    order = {"active": 0, "unknown": 1, "unchecked": 2, "bad": 3}
    return sorted(out, key=lambda a: order[a["status"]])


def tier(item):
    if item["booked"] <= 0:
        return "fyi"
    hard = item["kind"] in ("obsolete", "eol", "last_time_buy")
    return "act" if hard and not item["alt_active"] and item["ltb_qty"] > 0 else "watch"


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
    """dist_cache {part: {checked, mpn, offers:[...], alts: {mpn: {checked, offers}}}};
    notices [{id, received, subject, sender, web_link, notice{...}}]; news [{maker,
    found_at, notices:[...]}]; mpn_rows [(part, mpn)] or [(part, mpn, maker, source)];
    parts {part: Part}; demands {part: [Demand]}; stock/on_order/annual {part: qty}."""
    idx = mpn_index(mpn_rows, parts)
    approved = approved_numbers(mpn_rows)
    signals = defaultdict(list)

    for part, c in (dist_cache or {}).items():
        o = worst([o for o in c.get("offers") or []
                   if same_part(o, c.get("mpn"), approved.get(part, {}))])
        if o:
            signals[part].append(
                {
                    "kind": o["lifecycle"],
                    "source": "distributor",
                    "where": o.get("source", ""),
                    "date": c.get("checked"),
                    "detail": f"{o.get('source', '')}: {o.get('lifecycle_text') or o['lifecycle']}"
                              f" ({' '.join(x for x in (o.get('maker'), o.get('mpn')) if x)})",
                    "link": o.get("url", ""),
                    "last_order": "",
                    "replacements": [],
                }
            )
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
        alts = alternates(part, (dist_cache or {}).get(part) or {}, approved.get(part, {}))
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
                "alternates": alts,
                "alt_active": any(a["status"] == "active" for a in alts),
            }
        )
        items[-1]["tier"] = tier(items[-1])
    items.sort(
        key=lambda i: (
            TIERS.index(i["tier"]),
            RANK.get(i["kind"], 9),
            i["days_left"] if i["days_left"] is not None else 9999,
            -i["ltb_cost"],
        )
    )
    return {
        "today": today,
        "items": items,
        "counts": {k: sum(1 for i in items if i["kind"] == k) for k in RANK},
        "tiers": {t: sum(1 for i in items if i["tier"] == t) for t in TIERS},
    }
