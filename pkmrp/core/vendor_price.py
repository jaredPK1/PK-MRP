"""Vendor prices over time: are vendors raising prices on us, and where?

Mirrors Mark's Vendor Price Index on the dashboard (pk-dashboard vpi.py) and
adds what a buyer needs to act: the POs behind every number and a short
list of things to look at.

  * The headline is "same parts, this year vs last": every part bought from
    a vendor in both the last 12 months and the 12 before, at its average
    price, weighted by last year's quantity (Laspeyres). Volume and mix don't
    move it; price does. The extra dollars are what this year's quantities
    cost over last year's prices. The line is that comparison at each month
    end, so you see whether increases are speeding up or easing.
    Mark's dashboard chains month to month instead (start = 100). On parts
    whose unit price swings with lot size -- machined parts, catalog breaks --
    month-to-month chaining drifts (DigiKey read +136%, PCB Universe -71%
    in 12 months), so the year-over-year comparison is used here.
  * Prices are per stocking unit (the extract converts packs), so a PO for
    10 packs of 100 and one for 1,000 each compare.
  * A ratio wildly out of line (more than 4x up or down) is left out of the
    index and reported instead -- almost always a pack/each keying slip.

Alerts ("look at these"):

  price_up       the latest PO (open or received) costs 10%+ more per unit
                 than the one before it, from the same vendor, recently.
  over_std       an open PO priced 20%+ over the part's standard cost.
  cheaper_else   another vendor sold PK the same part 15%+ cheaper in the
                 last two years.
  vendor_drift   a vendor's whole index is up 8%+ in 12 months on real spend.
  price_odd      a price 4x off the last one -- check the unit / pack on the PO.

Each one carries the dollars at stake (the increase times the quantity on
order, or a year's quantity), so the list sorts by what matters.

Pure: DataFrames in, a JSON-ready dict out.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True)
class PricePolicy:
    months: int = 36  # receipts shown in the drill-down
    series_months: int = 24  # points on the "vs a year earlier" lines
    jump_pct: float = 0.10
    jump_min_impact: float = 2000.0
    recent_days: int = 120
    over_std_pct: float = 0.20
    over_std_min_impact: float = 2000.0
    drift_pct: float = 0.08
    drift_min_spend: float = 25000.0
    elsewhere_pct: float = 0.15
    elsewhere_days: int = 730
    elsewhere_min_impact: float = 2000.0
    odd_ratio: float = 4.0
    odd_min_value: float = 200.0


def _d(v):
    if v is None or v != v:
        return None
    return v.date() if hasattr(v, "date") else v


def _month(d):
    return f"{d.year:04d}-{d.month:02d}"


def yoy(rows, end, odd_ratio=4.0):
    """Same parts, this year vs last: rows [(date, item, qty, unit_price)].

    The year to `end` against the year before it, on the parts bought in
    both, each at its qty-weighted average price. Returns (change, extra
    dollars paid this year on those parts, share of this year's spend they
    cover, parts compared) -- or None when nothing was bought in both years.
    Weighted by last year's quantity (Laspeyres), so buying more or less of
    something doesn't move it; a part whose price moved more than odd_ratio
    either way is left out (a unit or pack slip, not a price).
    """
    a0, b0 = end - timedelta(days=365), end - timedelta(days=730)
    cur, prev = defaultdict(lambda: [0.0, 0.0]), defaultdict(lambda: [0.0, 0.0])
    for when, item, qty, price in rows:
        if a0 < when <= end:
            c = cur[item]
        elif b0 < when <= a0:
            c = prev[item]
        else:
            continue
        c[0] += qty * price
        c[1] += qty
    num = den = covered = 0.0
    n = 0
    spend = sum(c for c, _q in cur.values())
    for item, (ca, qa) in cur.items():
        cb, qb = prev.get(item, (0.0, 0.0))
        if qa <= 0 or qb <= 0:
            continue
        pa, pb = ca / qa, cb / qb
        r = pa / pb
        if r > odd_ratio or r < 1 / odd_ratio:
            continue
        num += pa * qb
        den += pb * qb
        covered += ca
        n += 1
    if not den:
        return None
    change = num / den - 1
    # what this year's spend on those parts would have been at last year's
    # prices, taken from the same index so the dollars and the % agree
    extra = covered - covered / (1 + change)
    return change, extra, (covered / spend if spend else 0.0), n


def yoy_series(rows, today, months=24, odd_ratio=4.0):
    """[(month, % change vs a year earlier)] at each month end, oldest first;
    months without two full years of data behind them are skipped."""
    first = min((r[0] for r in rows), default=None)
    out = []
    for k in range(months - 1, -1, -1):
        y, m = today.year, today.month - k
        while m <= 0:
            y, m = y - 1, m + 12
        end = today if k == 0 else (date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1))
        if first is None or first > end - timedelta(days=700):
            continue
        res = yoy(rows, end, odd_ratio)
        if res:
            out.append((f"{y:04d}-{m:02d}", round(res[0] * 100, 1)))
    return out


def _po_events(recs, opens):
    """Price events for one (vendor, part), oldest first: one per PO.

    A received PO is priced by its receipts (qty-weighted) and dated by its
    first receipt; an open PO not yet received is priced from the PO line
    and dated when it was placed.
    """
    by_po = {}
    for r in recs:
        e = by_po.setdefault(
            r["po"], {"po": r["po"], "date": r["date"], "cost": 0.0, "qty": 0.0, "open": False}
        )
        e["cost"] += r["qty"] * r["unit_price"]
        e["qty"] += r["qty"]
        e["date"] = min(e["date"], r["date"])
    for o in opens:
        if o["po"] in by_po:
            continue
        e = by_po.setdefault(
            o["po"],
            {"po": o["po"], "date": o["created"] or o["cur_due"], "cost": 0.0, "qty": 0.0, "open": True},
        )
        e["cost"] += o["qty_due"] * o["unit_price"]
        e["qty"] += o["qty_due"]
    out = []
    for e in by_po.values():
        if e["qty"] > 0 and e["date"]:
            out.append(dict(e, price=e["cost"] / e["qty"]))
    out.sort(key=lambda e: (e["date"], e["po"]))
    return out


def build(receipts, open_pos, names, descriptions, on_time, today, policy=None):
    """Everything the Vendor prices page shows.

    receipts   DataFrame from extract.receipt_prices
    open_pos   DataFrame from extract.open_po_prices
    names      {vendor_id: name}
    on_time    {vendor_id: on-time %} from analytics.vendor_delivery
    """
    policy = policy or PricePolicy()
    since = today - timedelta(days=round(policy.months * 30.44))
    index_since = today - timedelta(days=730 + round(policy.series_months * 30.44))
    year_ago = today - timedelta(days=365)

    recs = defaultdict(list)  # (vendor, part) -> receipt rows (drill-down window)
    idx_rows = defaultdict(list)  # vendor -> (date, part, qty, price), index window
    for r in receipts.itertuples(index=False):
        when = _d(r.date)
        if when is None or when < index_since or not r.vendor_id or not (r.qty > 0) or not (r.unit_price > 0):
            continue
        idx_rows[r.vendor_id].append((when, r.part, float(r.qty), float(r.unit_price)))
        if when < since:
            continue
        recs[(r.vendor_id, r.part)].append(
            {
                "date": when,
                "po": r.po,
                "line": r.line,
                "qty": float(r.qty),
                "unit_price": float(r.unit_price),
                "std": float(r.std_cost) if r.std_cost == r.std_cost else None,
                "invoice": r.invoice or "",
            }
        )
    opens = defaultdict(list)
    for o in open_pos.itertuples(index=False):
        if not o.vendor_id or not (o.unit_price > 0):
            continue
        opens[(o.vendor_id, o.part)].append(
            {
                "po": o.po,
                "line": o.line,
                "created": _d(o.created),
                "cur_due": _d(o.cur_due),
                "qty_due": float(o.qty_due),
                "unit_price": float(o.unit_price),
                "std": float(o.std_cost) if o.std_cost == o.std_cost else None,
            }
        )

    # ---- same parts, this year vs last: everyone, and per vendor
    all_rows = [(w, (v, p), q, pr) for v, rows in idx_rows.items() for w, p, q, pr in rows]
    overall = yoy(all_rows, today, policy.odd_ratio)
    overall_series = yoy_series(all_rows, today, policy.series_months, policy.odd_ratio)

    alerts = []
    vendors, parts_by_vendor, detail = [], {}, {}
    for v, rows in idx_rows.items():
        res = yoy(rows, today, policy.odd_ratio)
        change, extra, cover, n = res if res else (None, 0.0, 0.0, 0)
        ttm_rows = [(q, pr, p) for w, p, q, pr in rows if w > year_ago]
        ttm_spend = sum(q * pr for q, pr, _p in ttm_rows)
        if not ttm_rows and not res:
            continue
        name = names.get(v, v)
        vendors.append(
            {
                "vendor_id": v,
                "vendor": name,
                "change_12m": round(change * 100, 1) if change is not None else None,
                "extra_12m": round(extra, 2),
                "compared_parts": n,
                "coverage_pct": round(cover * 100),
                "ttm_spend": round(ttm_spend, 2),
                "parts": len({p for _q, _pr, p in ttm_rows}),
                "receipts_12m": len(ttm_rows),
                "on_time_pct": on_time.get(v),
                "series": yoy_series(rows, today, 12, policy.odd_ratio),
            }
        )
        if (
            change is not None
            and change >= policy.drift_pct
            and ttm_spend >= policy.drift_min_spend
            and extra >= policy.jump_min_impact
        ):
            alerts.append(
                {
                    "kind": "vendor_drift",
                    "vendor_id": v,
                    "vendor": name,
                    "part": None,
                    "impact": round(extra, 2),
                    "what": f"Same parts cost {change * 100:.0f}% more than a year earlier ({n} part{'s' if n != 1 else ''}, {cover * 100:.0f}% of this year's ${ttm_spend:,.0f}); ${extra:,.0f} more paid this year",
                    "do": "Ask for the reason (material, labour, tariff) and whether quantity or a longer agreement would hold the price. The parts list shows the biggest movers.",
                }
            )

    # ---- per part, per vendor
    latest_by_part = defaultdict(list)  # part -> [(vendor, last event)]
    for key in set(recs) | set(opens):
        v, p = key
        rows = sorted(recs.get(key, []), key=lambda r: (r["date"], r["po"]))
        ol = opens.get(key, [])
        events = _po_events(rows, ol)
        if not events:
            continue
        last = events[-1]
        before = [e for e in events if e["date"] <= year_ago]
        base = before[-1] if before else events[0]
        ttm_qty = sum(r["qty"] for r in rows if r["date"] >= year_ago)
        ttm_spend = sum(r["qty"] * r["unit_price"] for r in rows if r["date"] >= year_ago)
        std = next((r["std"] for r in reversed(rows) if r["std"]), None) or next(
            (o["std"] for o in ol if o["std"]), None
        )
        change = last["price"] / base["price"] - 1 if base["price"] else 0.0
        open_qty = sum(o["qty_due"] for o in ol)
        months = defaultdict(lambda: [0.0, 0.0])
        for r in rows:
            mm = months[_month(r["date"])]
            mm[0] += r["qty"] * r["unit_price"]
            mm[1] += r["qty"]
        row = {
            "part": p,
            "description": descriptions.get(p, ""),
            "first_price": round(events[0]["price"], 4),
            "base_price": round(base["price"], 4),
            "base_date": base["date"],
            "last_price": round(last["price"], 4),
            "last_date": last["date"],
            "last_po": last["po"],
            "last_open": last["open"],
            "change_pct": round(change * 100, 1),
            "ttm_qty": ttm_qty,
            "ttm_spend": round(ttm_spend, 2),
            "impact": round((last["price"] - base["price"]) * max(ttm_qty, open_qty), 2),
            "std": round(std, 4) if std else None,
            "open_qty": open_qty,
            "pos": len(events),
            "series": [(m, round(c / q, 4)) for m, (c, q) in sorted(months.items()) if q],
        }
        parts_by_vendor.setdefault(v, []).append(row)
        if last["date"] >= today - timedelta(days=policy.elsewhere_days):
            latest_by_part[p].append((v, last, max(ttm_qty, open_qty)))

        # receipts + open lines, flagged, for the drill-down
        lines, prev = [], None
        for e in events:
            flag = ""
            if prev:
                ratio = e["price"] / prev if prev else 1
                if ratio > policy.odd_ratio or ratio < 1 / policy.odd_ratio:
                    flag = "odd"
                elif ratio >= 1 + policy.jump_pct:
                    flag = "up"
                elif ratio <= 1 - policy.jump_pct:
                    flag = "down"
            prev = e["price"]
            e["flag"] = flag
        flag_of = {e["po"]: e["flag"] for e in events}
        for r in rows:
            lines.append(
                {
                    "date": r["date"],
                    "po": r["po"],
                    "line": r["line"],
                    "qty": r["qty"],
                    "unit_price": round(r["unit_price"], 4),
                    "std": round(r["std"], 4) if r["std"] else None,
                    "ppv": round((r["unit_price"] - r["std"]) * r["qty"], 2) if r["std"] else None,
                    "invoice": r["invoice"],
                    "open": False,
                    "flag": flag_of.get(r["po"], ""),
                }
            )
        for o in ol:
            lines.append(
                {
                    "date": o["created"],
                    "po": o["po"],
                    "line": o["line"],
                    "qty": o["qty_due"],
                    "unit_price": round(o["unit_price"], 4),
                    "std": round(o["std"], 4) if o["std"] else None,
                    "ppv": round((o["unit_price"] - o["std"]) * o["qty_due"], 2) if o["std"] else None,
                    "invoice": "",
                    "open": True,
                    "due": o["cur_due"],
                    "flag": flag_of.get(o["po"], ""),
                }
            )
        lines.sort(key=lambda x: (x["date"] or date.min, x["po"]), reverse=True)
        detail[f"{v}|{p}"] = lines

        # ---- alerts for this part
        name = names.get(v, v)
        desc = descriptions.get(p, "")
        if len(events) >= 2:
            prev_e, cur = events[-2], events[-1]
            ratio = cur["price"] / prev_e["price"] if prev_e["price"] else 1.0
            recent = cur["open"] or cur["date"] >= today - timedelta(days=policy.recent_days)
            qty_basis = cur["qty"] if cur["open"] else max(ttm_qty, cur["qty"])
            if recent and (ratio > policy.odd_ratio or ratio < 1 / policy.odd_ratio):
                if cur["price"] * cur["qty"] >= policy.odd_min_value or prev_e["price"] * cur["qty"] >= policy.odd_min_value:
                    alerts.append(
                        {
                            "kind": "price_odd",
                            "vendor_id": v,
                            "vendor": name,
                            "part": p,
                            "description": desc,
                            "po": cur["po"],
                            "impact": round(abs(cur["price"] - prev_e["price"]) * cur["qty"], 2),
                            "what": f"PO {cur['po']} at ${cur['price']:,.4g} each vs ${prev_e['price']:,.4g} on PO {prev_e['po']} ({ratio:.1f}x)",
                            "do": "Almost always a pack/each slip on the PO line or the invoice. Check the unit and cost conversion before the invoice is paid.",
                        }
                    )
            elif recent and ratio >= 1 + policy.jump_pct:
                imp = (cur["price"] - prev_e["price"]) * qty_basis
                if imp >= policy.jump_min_impact:
                    alerts.append(
                        {
                            "kind": "price_up",
                            "vendor_id": v,
                            "vendor": name,
                            "part": p,
                            "description": desc,
                            "po": cur["po"],
                            "open": cur["open"],
                            "impact": round(imp, 2),
                            "what": f"{'Open ' if cur['open'] else ''}PO {cur['po']} at ${cur['price']:,.2f} each, up {(ratio - 1) * 100:.0f}% from ${prev_e['price']:,.2f} on PO {prev_e['po']} ({prev_e['date'].strftime('%b %Y')})",
                            "do": "Ask the vendor why. If there's a quote or quantity break, check the PO matches it; if not, check another source.",
                        }
                    )
        seen_po = set()
        for o in ol:
            if o["po"] in seen_po:
                continue
            if o["std"] and o["unit_price"] >= o["std"] * (1 + policy.over_std_pct):
                seen_po.add(o["po"])
                o = dict(o, qty_due=sum(x["qty_due"] for x in ol if x["po"] == o["po"]))
                imp = (o["unit_price"] - o["std"]) * o["qty_due"]
                already = any(
                    a["kind"] in ("price_up", "price_odd") and a["part"] == p and a["vendor_id"] == v
                    for a in alerts
                )
                if imp >= policy.over_std_min_impact and not already:
                    alerts.append(
                        {
                            "kind": "over_std",
                            "vendor_id": v,
                            "vendor": name,
                            "part": p,
                            "description": desc,
                            "po": o["po"],
                            "open": True,
                            "impact": round(imp, 2),
                            "what": f"Open PO {o['po']} at ${o['unit_price']:,.2f} each, {(o['unit_price'] / o['std'] - 1) * 100:.0f}% over standard ${o['std']:,.2f} on {o['qty_due']:g} due",
                            "do": "Either the PO price is high or the standard is stale. Confirm the price with the vendor; if it's right, the standard needs updating.",
                        }
                    )

    # ---- cheaper elsewhere: same part, another vendor, lately. Checked for
    # the vendor bought from most recently and for any vendor with a PO still
    # open -- an open PO at the dearer vendor is the one that can still change.
    for p, lst in latest_by_part.items():
        if len(lst) < 2:
            continue
        newest = max(lst, key=lambda x: x[1]["date"])[0]
        for cur_v, cur, qty in lst:
            if cur_v != newest and not cur["open"]:
                continue
            others = [x for x in lst if x[0] != cur_v]
            best = min(others, key=lambda x: x[1]["price"])
            if not best[1]["price"] or cur["price"] < best[1]["price"] * (1 + policy.elsewhere_pct):
                continue
            imp = (cur["price"] - best[1]["price"]) * (cur["qty"] if cur["open"] else qty)
            if imp < policy.elsewhere_min_impact:
                continue
            alerts.append(
                {
                    "kind": "cheaper_else",
                    "vendor_id": cur_v,
                    "vendor": names.get(cur_v, cur_v),
                    "part": p,
                    "description": descriptions.get(p, ""),
                    "po": cur["po"],
                    "open": cur["open"],
                    "impact": round(imp, 2),
                    "what": f"{'Open PO' if cur['open'] else 'Paying'} {'' if cur['open'] else '$' + format(cur['price'], ',.2f') + ' on PO '}{cur['po']}{(' at $' + format(cur['price'], ',.2f') + ' for ' + format(cur['qty'], 'g')) if cur['open'] else ''}; {names.get(best[0], best[0]).title()} sold it for ${best[1]['price']:,.2f} on PO {best[1]['po']} ({best[1]['date'].strftime('%b %Y')})",
                    "do": "Find out why the source changed (quality, lead time, minimum). If there's no reason, quote the cheaper vendor"
                    + (" before this PO ships." if cur["open"] else "."),
                }
            )

    for rows in parts_by_vendor.values():
        rows.sort(key=lambda r: (-r["impact"], r["part"]))
    vendors.sort(key=lambda r: -r["ttm_spend"])
    alerts.sort(key=lambda a: -a["impact"])
    change, extra, cover, n = overall if overall else (None, 0.0, 0.0, 0)
    return {
        "today": today,
        "since": since,
        "overall": {
            "series": overall_series,
            "change_12m": round(change * 100, 1) if change is not None else None,
            "extra_12m": round(extra, 2),
            "coverage_pct": round(cover * 100),
            "compared_parts": n,
            "ttm_spend": round(sum(v["ttm_spend"] for v in vendors), 2),
        },
        "vendors": vendors,
        "parts": parts_by_vendor,
        "detail": detail,
        "alerts": alerts,
        "alert_counts": {
            k: sum(1 for a in alerts if a["kind"] == k)
            for k in ("price_up", "over_std", "cheaper_else", "vendor_drift", "price_odd")
        },
    }
