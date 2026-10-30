"""Sourcing ideas: where buying differently would save money or trouble.

Vendor prices (core/vendor_price.py) says what happened to prices. This says
what to do about it, in five kinds of suggestion, each with the dollars a
year it's worth and the evidence behind it:

  switch        another vendor has sold PK the part for less, and isn't
                worse on delivery or returns. Weighs price, on-time %,
                returns (DMRs) and real lead time -- a cheaper vendor that
                ships late or sends parts back isn't a saving.
  price_break   the vendor's quoted break makes a slightly bigger order cost
                the same or less (or a little more for parts booked orders
                will use soon). From Part_Vendor, sanity-checked against what
                PK actually paid, because those rows are kept unevenly.
  make          a part PK buys could be built here: its bill of parts costs
                well under the price paid. Labour isn't in MAX for a bought
                part, so it says how many hours would still break even at the
                shop rate -- and whether PK has built it before (62-3850-00G).
  buy           a part PK builds has been bought from a vendor for less than
                its material plus labour at the shop rate -- or takes a lot of
                labour, which a capacity-short shop could buy instead.
  negotiate     vendors worth a conversation: big spend with rising prices,
                or many small POs that an annual agreement or blanket would
                turn into one.
  standard      parts whose standard cost is far from what PK pays (a
                worklist for whoever keeps costs; it skews PPV and margins).

Pure: plain data in, a JSON-ready dict out.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import timedelta


@dataclass(frozen=True)
class SourcingPolicy:
    min_savings: float = 2000.0  # $ a year for a suggestion to show
    switch_pct: float = 0.10  # alternative at least this much cheaper
    switch_on_time_slack: float = 15.0  # points of on-time the alternative may give up
    switch_return_slack: float = 0.05  # extra share of units returned it may have
    switch_days: int = 1095  # the alternative sold it to PK within this many days
    break_extra_days: int = 180  # extra units must be needed within this window
    break_price_band: tuple = (0.5, 1.6)  # quoted break vs paid, to trust the row
    shop_rate: float = 171.0  # $/hour, fully loaded (labour absorption audit)
    make_min_gap_pct: float = 0.25  # parts cost at least this far under the price paid
    buy_pct: float = 0.15  # vendor at least this much under make cost
    labor_hours_flag: float = 4.0  # hours a unit that make it an outsourcing candidate
    negotiate_spend: float = 50000.0
    negotiate_rise_pct: float = 5.0
    small_po_count: int = 24  # POs a year ...
    small_po_avg: float = 2000.0  # ... averaging under this
    standard_gap_pct: float = 0.15
    standard_min_spend: float = 5000.0


def _d(v):
    if v is None or v != v:
        return None
    return v.date() if hasattr(v, "date") else v


def annual_qty(part, booked, received_12m):
    """A year's quantity: the larger of what booked orders need in the next 12
    months and what was received in the last 12."""
    return max(booked.get(part, 0.0), received_12m.get(part, 0.0))


def booked_12m(demands, today):
    """{part: qty booked orders need in the next 365 days}."""
    end = today + timedelta(days=365)
    out = defaultdict(float)
    for part, ds in demands.items():
        out[part] = sum(d.qty for d in ds if d.date <= end)
    return out


def _po_qty(vp, vid, part, po):
    return sum(line["qty"] for line in vp["detail"].get(f"{vid}|{part}", []) if line["po"] == po)


def switches(vp, delivery, returns, annual, names, descriptions, policy):
    """Cheaper vendors that aren't worse on delivery or returns.

    A gap of more than 2.5x is usually a different job, not a better price --
    raw vs finished (Duyck delivers anodized; a shop quoting raw leaves the
    finishing lot charge to PK), bare board vs assembled, a one-off vs a lot
    -- so those are kept but marked "check the scope"."""
    on_time = {v["vendor_id"]: v.get("on_time_pct") for v in delivery}
    lead = {v["vendor_id"]: v.get("real_lead_wd") for v in delivery}
    by_part = defaultdict(list)
    for vid, rows in vp["parts"].items():
        for r in rows:
            by_part[r["part"]].append((vid, r))
    today = vp["today"]
    out = []
    for part, lst in by_part.items():
        if len(lst) < 2:
            continue
        cur_v, cur = max(lst, key=lambda x: (x[1]["last_open"], str(x[1]["last_date"])))
        qty = annual(part)
        if not qty:
            continue
        for alt_v, alt in lst:
            if alt_v == cur_v:
                continue
            last = _d(alt["last_date"])
            if last and (today - last).days > policy.switch_days:
                continue
            if alt["last_price"] > cur["last_price"] * (1 - policy.switch_pct):
                continue
            ot_c, ot_a = on_time.get(cur_v), on_time.get(alt_v)
            if ot_c is not None and ot_a is not None and ot_a < ot_c - policy.switch_on_time_slack:
                continue
            rr_c, rr_a = returns.get((cur_v, part), 0.0), returns.get((alt_v, part), 0.0)
            if rr_a > rr_c + policy.switch_return_slack:
                continue
            saving = (cur["last_price"] - alt["last_price"]) * qty
            if saving < policy.min_savings:
                continue
            scope = alt["last_price"] < cur["last_price"] / 2.5
            q_now = _po_qty(vp, cur_v, part, cur["last_po"])
            q_alt = _po_qty(vp, alt_v, part, alt["last_po"])
            out.append(
                {
                    "kind": "switch",
                    "part": part,
                    "description": descriptions.get(part, ""),
                    "vendor_id": cur_v,
                    "vendor": names.get(cur_v, cur_v),
                    "to_vendor_id": alt_v,
                    "to_vendor": names.get(alt_v, alt_v),
                    "saving": round(saving, 2),
                    "check_scope": scope,
                    "evidence": {
                        "now_qty": q_now,
                        "alt_qty": q_alt,
                        "now_price": cur["last_price"],
                        "now_po": cur["last_po"],
                        "alt_price": alt["last_price"],
                        "alt_po": alt["last_po"],
                        "alt_date": alt["last_date"],
                        "on_time_now": ot_c,
                        "on_time_alt": ot_a,
                        "returns_now_pct": round(rr_c * 100, 1),
                        "returns_alt_pct": round(rr_a * 100, 1),
                        "lead_now_wd": lead.get(cur_v),
                        "lead_alt_wd": lead.get(alt_v),
                        "annual_qty": qty,
                    },
                    "what": f"{names.get(alt_v, alt_v).title()} sold it at ${alt['last_price']:,.2f} ({q_alt:g} on PO {alt['last_po']}) vs ${cur['last_price']:,.2f} now ({q_now:g} on PO {cur['last_po']})"
                    + (
                        f"; on time {ot_a:.0f}% vs {ot_c:.0f}%"
                        if ot_a is not None and ot_c is not None
                        else ""
                    )
                    + (f"; returns {rr_a * 100:.0f}% vs {rr_c * 100:.0f}%" if rr_a or rr_c else ""),
                    "do": (
                        "Big gap: check it's the same scope first (finished vs raw, assembled vs bare board, same rev and lot size). If it is, quote the next order with both."
                        if scope
                        else "Quote the next order with both. Check the alternative is still approved for this rev before switching."
                    ),
                }
            )
    # best alternative per part only
    best = {}
    for s in out:
        if s["part"] not in best or s["saving"] > best[s["part"]]["saving"]:
            best[s["part"]] = s
    return list(best.values())


def _price_at(breaks, q):
    """Unit price for quantity q from [(break qty, price)] ascending."""
    price = None
    for b, p in breaks:
        if q >= b:
            price = p
    return price


def price_breaks(buys, breaks_by, paid, booked_soon, names, policy):
    """Order a little more where the vendor's quoted break pays for it.

    buys        [{part, qty, vendor_id, vendor, unit_cost}] buys to place now
    breaks_by   {(part, vendor_id): [(qty, unit price)]}
    paid        {(vendor_id, part): last price paid}
    booked_soon {part: qty booked orders need within break_extra_days, beyond this buy}
    """
    lo, hi = policy.break_price_band
    out = []
    for b in buys:
        key = (b["part"], b.get("vendor_id") or "")
        brs = sorted(breaks_by.get(key, []))
        last = paid.get((key[1], key[0]))
        if len(brs) < 2 or not last:
            continue
        if not all(lo <= p / last <= hi for _q, p in brs):
            continue  # per-pack vs per-each row, or a stale quote
        q = b["qty"]
        p_now = _price_at(brs, q) or brs[0][1]
        for bq, bp in brs:
            if bq <= q:
                continue
            extra = bq - q
            used_soon = booked_soon.get(b["part"], 0.0) >= extra
            total_now, total_up = q * p_now, bq * bp
            if total_up <= total_now or (used_soon and bp < p_now):
                saving = (p_now - bp) * bq if used_soon else total_now - total_up
                if saving <= 0 and total_up > total_now:
                    continue
                out.append(
                    {
                        "kind": "price_break",
                        "part": b["part"],
                        "description": b.get("description", ""),
                        "vendor_id": key[1],
                        "vendor": b.get("vendor") or names.get(key[1], key[1]),
                        "saving": round(max(saving, total_now - total_up), 2),
                        "evidence": {
                            "qty": q,
                            "price": p_now,
                            "break_qty": bq,
                            "break_price": bp,
                            "used_soon": used_soon,
                        },
                        "what": f"Buying {q:g} at ${p_now:,.2f}; {bq:g} is ${bp:,.2f} each — "
                        + (
                            "costs no more in total"
                            if total_up <= total_now
                            else f"{extra:g} extra that booked orders use within {policy.break_extra_days // 30} months"
                        ),
                        "do": f"Order {bq:g} instead of {q:g}, if the quote is current.",
                    }
                )
                break
    return [s for s in out if s["saving"] >= min(policy.min_savings, 250.0)]


def make_or_buy(
    parts,
    bom,
    unit_costs,
    make_costs,
    built,
    paid_by_part,
    annual,
    names_by_part,
    descriptions,
    policy,
    sold=frozenset(),
):
    """Bought parts PK could build, and built parts PK could buy.

    bom          {parent: [(component, qty_per)]} all type codes, latest rows
    unit_costs   {part: standard unit cost}
    make_costs   {part: (material, labor, hours)}
    built        {part: (work orders, qty, last built)}
    paid_by_part {part: (unit price, vendor_id, po)} latest purchase
    sold         parts customers order directly (systems): never outsourcing candidates
    """
    out = []
    for part, info in parts.items():
        qty = annual(part)
        if not qty:
            continue
        if info.type == "B" and part in bom and part in paid_by_part:
            comps = bom[part]
            parts_cost = sum(q * (unit_costs.get(c) or 0.0) for c, q in comps)
            if not parts_cost or any(not unit_costs.get(c) for c, _q in comps):
                continue
            price, vid, po = paid_by_part[part]
            gap = price - parts_cost
            if gap < price * policy.make_min_gap_pct:
                continue
            hours_ok = gap / policy.shop_rate
            if hours_ok < 0.25:
                continue
            b = built.get(part)
            saving_at_1h = (gap - policy.shop_rate) * qty
            if saving_at_1h < policy.min_savings and not b:
                continue
            out.append(
                {
                    "kind": "make",
                    "part": part,
                    "description": descriptions.get(part, ""),
                    "vendor_id": vid,
                    "vendor": names_by_part.get(part, vid),
                    "saving": round(max(saving_at_1h, 0.0), 2),
                    "evidence": {
                        "price": price,
                        "po": po,
                        "parts_cost": round(parts_cost, 2),
                        "components": [c for c, _q in comps][:8],
                        "break_even_hours": round(hours_ok, 1),
                        "built_before": b[0] if b else 0,
                        "last_built": b[2] if b else None,
                        "annual_qty": qty,
                    },
                    "what": f"Buying at ${price:,.2f}; its parts cost ${parts_cost:,.2f}. Building pays if it takes under {hours_ok:.1f} h at ${policy.shop_rate:.0f}/h"
                    + (
                        f" — PK has built it on {b[0]} work order{'s' if b[0] != 1 else ''}"
                        if b
                        else ""
                    ),
                    "do": (
                        "Ask production how long it takes to build. If it's under the break-even, make it a built part (an ECN) and buy the components."
                        if b
                        else "Check the bill first: on a bought part MAX often lists only what PK sends the vendor, not the whole build. If it is complete, ask production how long it would take."
                    ),
                }
            )
        elif info.type == "A" and part in make_costs:
            material, labor, hours = make_costs[part]
            if not hours and not material:
                continue
            make_cost = material + hours * policy.shop_rate
            bought = paid_by_part.get(part)
            if bought and bought[0] <= make_cost * (1 - policy.buy_pct):
                saving = (make_cost - bought[0]) * qty
                if saving >= policy.min_savings:
                    out.append(
                        {
                            "kind": "buy",
                            "part": part,
                            "description": descriptions.get(part, ""),
                            "vendor_id": bought[1],
                            "vendor": names_by_part.get(part, bought[1]),
                            "saving": round(saving, 2),
                            "evidence": {
                                "make_cost": round(make_cost, 2),
                                "material": round(material, 2),
                                "hours": round(hours, 2),
                                "price": bought[0],
                                "po": bought[2],
                                "annual_qty": qty,
                            },
                            "what": f"Built here for about ${make_cost:,.2f} (${material:,.2f} material + {hours:.1f} h); bought for ${bought[0]:,.2f} on PO {bought[2]}",
                            "do": "Quote it with that vendor again. Buying it also frees the build hours.",
                        }
                    )
            elif (
                part not in sold
                and hours >= policy.labor_hours_flag
                and hours * qty * policy.shop_rate >= policy.min_savings * 5
            ):
                out.append(
                    {
                        "kind": "buy",
                        "part": part,
                        "description": descriptions.get(part, ""),
                        "vendor_id": "",
                        "vendor": "",
                        "saving": 0.0,
                        "hours_year": round(hours * qty, 1),
                        "evidence": {
                            "make_cost": round(make_cost, 2),
                            "material": round(material, 2),
                            "hours": round(hours, 2),
                            "annual_qty": qty,
                        },
                        "what": f"{hours:.1f} h a unit, about {hours * qty:,.0f} h a year for booked orders — never quoted outside",
                        "do": "If build hours are the constraint, get a quote: anything under its material plus labour frees the time for systems.",
                    }
                )
    return out


def negotiate(vp, po_counts, names, policy):
    """Vendors worth an annual agreement or a blanket."""
    out = []
    for v in vp["vendors"]:
        vid, spend = v["vendor_id"], v["ttm_spend"]
        rise = v.get("change_12m")
        pos = po_counts.get(vid, 0)
        reasons = []
        if (
            spend >= policy.negotiate_spend
            and rise is not None
            and rise >= policy.negotiate_rise_pct
        ):
            reasons.append(f"same parts up {rise:.0f}% on ${spend:,.0f} a year")
        if pos >= policy.small_po_count and pos and spend / pos < policy.small_po_avg:
            reasons.append(f"{pos} POs a year averaging ${spend / pos:,.0f}")
        if not reasons:
            continue
        # a 3% better price on a year's spend, or half the PO handling saved
        saving = max(spend * 0.03, (pos * 75.0 / 2) if pos >= policy.small_po_count else 0.0)
        out.append(
            {
                "kind": "negotiate",
                "part": None,
                "description": "",
                "vendor_id": vid,
                "vendor": names.get(vid, v["vendor"]),
                "saving": round(saving, 2),
                "evidence": {
                    "spend": spend,
                    "change_12m": rise,
                    "pos_12m": pos,
                    "on_time_pct": v.get("on_time_pct"),
                },
                "what": "; ".join(reasons),
                "do": "Offer a 12-month forecast or blanket for a fixed price and fewer POs. The estimate assumes 3% off, or half the PO handling.",
            }
        )
    return [s for s in out if s["saving"] >= policy.min_savings]


def standards(vp, descriptions, policy):
    """Parts whose standard cost is far from what PK pays."""
    out = []
    for vid, rows in vp["parts"].items():
        for r in rows:
            std, last = r.get("std"), r["last_price"]
            if not std or r["ttm_spend"] < policy.standard_min_spend:
                continue
            gap = last / std - 1
            if abs(gap) < policy.standard_gap_pct:
                continue
            out.append(
                {
                    "kind": "standard",
                    "part": r["part"],
                    "description": descriptions.get(r["part"], ""),
                    "vendor_id": vid,
                    "vendor": "",
                    "saving": 0.0,
                    "ppv_year": round((last - std) * r["ttm_qty"], 2),
                    "evidence": {
                        "std": std,
                        "last_price": last,
                        "last_po": r["last_po"],
                        "gap_pct": round(gap * 100, 1),
                        "ttm_qty": r["ttm_qty"],
                    },
                    "what": f"Standard ${std:,.2f}, paying ${last:,.2f} ({gap * 100:+.0f}%)",
                    "do": "Update the standard in the next cost roll, or find out why the price moved.",
                }
            )
    out.sort(key=lambda s: -abs(s["ppv_year"]))
    return out


def build(
    vp,
    delivery,
    dmrs,
    breaks,
    make_costs,
    wo_builds,
    buys,
    parts,
    bom_df,
    demands,
    names,
    today,
    policy=None,
):
    """Everything the Sourcing ideas page shows."""
    policy = policy or SourcingPolicy()
    descriptions = {p: v.description for p, v in parts.items()}
    booked = booked_12m(demands, today)
    received = defaultdict(float)
    paid = {}
    paid_by_part = {}
    for vid, rows in vp["parts"].items():
        for r in rows:
            received[r["part"]] += r["ttm_qty"]
            paid[(vid, r["part"])] = r["last_price"]
            prev = paid_by_part.get(r["part"])
            if prev is None or str(r["last_date"]) > prev[3]:
                paid_by_part[r["part"]] = (r["last_price"], vid, r["last_po"], str(r["last_date"]))

    def annual(part):
        return annual_qty(part, booked, received)

    # returns: share of units sent back, per (vendor, part)
    rec_qty = defaultdict(float)
    for vid, rows in vp["parts"].items():
        for r in rows:
            for line in vp["detail"].get(f"{vid}|{r['part']}", []):
                if not line["open"]:
                    rec_qty[(vid, r["part"])] += line["qty"]
    returns = {}
    for r in dmrs.itertuples(index=False):
        got = rec_qty.get((r.vendor_id, r.part), 0.0)
        if got:
            returns[(r.vendor_id, r.part)] = min(float(r.qty_returned) / got, 1.0)

    breaks_by = defaultdict(list)
    for r in breaks.itertuples(index=False):
        for q, c in ((r.break1, r.cost1), (r.break2, r.cost2), (r.break3, r.cost3)):
            if q and q == q and c and c == c and q > 0 and c > 0:
                breaks_by[(r.part, r.vendor_id)].append((float(q), float(c)))

    name_to_id = {n: i for i, n in names.items()}
    soon = today + timedelta(days=policy.break_extra_days)
    buy_rows = []
    for b in buys:
        vid = name_to_id.get(b.get("vendor") or "", "")
        need_soon = sum(d.qty for d in demands.get(b["part"], []) if d.date <= soon)
        buy_rows.append(dict(b, vendor_id=vid, _soon=max(need_soon - b["qty"], 0.0)))
    booked_soon = {b["part"]: b["_soon"] for b in buy_rows}

    bom = defaultdict(list)
    for r in bom_df.itertuples(index=False):
        bom[r.parent].append((r.component, float(r.qty_per)))
    unit_costs = {p: float(v.unit_cost or 0.0) for p, v in parts.items()}
    mc = {
        r.part: (float(r.material or 0), float(r.labor or 0), float(r.hours or 0))
        for r in make_costs.itertuples(index=False)
    }
    built = {
        r.part: (int(r.work_orders), float(r.qty_built or 0), _d(r.last_built))
        for r in wo_builds.itertuples(index=False)
    }
    names_by_part = {p: names.get(v[1], v[1]) for p, v in paid_by_part.items()}

    since = today - timedelta(days=365)
    po_counts = defaultdict(set)
    for vid, rows in vp["parts"].items():
        for r in rows:
            for line in vp["detail"].get(f"{vid}|{r['part']}", []):
                if not line["open"] and line["date"] and line["date"] >= since:
                    po_counts[vid].add(line["po"])

    ideas = (
        switches(vp, delivery, returns, annual, names, descriptions, policy)
        + price_breaks(buy_rows, breaks_by, paid, booked_soon, names, policy)
        + make_or_buy(
            parts,
            bom,
            unit_costs,
            mc,
            built,
            {p: v[:3] for p, v in paid_by_part.items()},
            annual,
            names_by_part,
            descriptions,
            policy,
            sold={
                p.root_part for ds in demands.values() for d in ds for p in d.pegs if p.kind == "so"
            },
        )
        + negotiate(vp, {k: len(v) for k, v in po_counts.items()}, names, policy)
    )
    ideas.sort(key=lambda s: (-s["saving"], -s.get("hours_year", 0.0), s["part"] or ""))
    std = standards(vp, descriptions, policy)
    counts = defaultdict(int)
    for s in ideas:
        counts[s["kind"]] += 1
    return {
        "today": today,
        "policy": {"shop_rate": policy.shop_rate, "min_savings": policy.min_savings},
        "ideas": ideas,
        "standards": std,
        "counts": dict(counts),
        # ideas flagged "check the scope" stay out of the headline
        "savings": round(sum(s["saving"] for s in ideas if not s.get("check_scope")), 2),
    }
