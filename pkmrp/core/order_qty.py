"""How many to order: one sensible PO instead of a new one every week.

Netting plans lot-for-lot -- one planned buy per demand -- and the buy list
shows only those due in the next five working days. On a cheap part with a
steady backlog that is the minimum, and it comes back a few days later as
the next slice: Rob ordered 14 of 35-0126-00G ($36 cable) on 10/29 and the
list asked Aaron for 15 more the next morning, with 114 still behind it.

This sizes each buy the way a buyer would if they had the time:

  * cover booked demand for an economic stretch of weeks. The stretch
    balances the cost of handling a PO line (placing, receiving, invoicing,
    freight) against carrying the stock: T = sqrt(2*S / (h * D * c)), where
    D is the booked demand rate and c the unit cost. A $36 cable used ~10 a
    week gets ~9 weeks; a $40K sampling head stays one order per need.
  * only booked demand -- the backlog is still the plan. The stretch picks
    which of the part's planned buys go on this order; it never invents
    quantity beyond them.
  * never less than this week's minimum, rounded once to MAX's min/multiple
    or pack, capped in weeks and in extra dollars.
  * committed (long-lead) parts cover a fixed stretch (13 weeks) of booked
    orders. They were left to their blanket plan, but no blanket is placed
    in MAX, so buyers got a fresh slice every few days: Haydon Kerk motors
    went on three POs in eight days (70111310, 70111350, 70111387), each
    priced at a smaller break -- 37-0007-01G at $163.35 for 10 against
    $143.58 for 30 the same week.
  * rounded up to the vendor's next quoted price break (Part_Vendor) when
    booked orders inside the cover cap use the extra and it's within the
    spend cap -- it never buys past booked demand to reach one.
  * a PO for the part placed in the last few days is named, so the buyer
    can add to it instead of cutting a second PO.

Pure: plain data in, dicts out.
"""

import math
from dataclasses import dataclass
from datetime import timedelta

from .calendar import plus_workdays
from .netting import _round_order


@dataclass(frozen=True)
class OrderPolicy:
    order_cost: float = 75.0  # $ per PO line: place, receive, invoice, freight share
    holding_rate: float = 0.25  # carrying cost per year, as a share of unit cost
    min_cover_weeks: float = 2.0
    max_cover_weeks: float = 26.0
    max_extra_spend: float = 15000.0  # $ above this week's minimum, at most
    min_rate_weeks: float = 13.0  # demand rate is spread over at least this many weeks
    no_cost_weeks: float = 8.0  # no cost in MAX: a middle-of-the-road stretch
    add_to_po_days: int = 14  # a PO this recent is "the one to add to"
    committed_cover_weeks: float = 13.0  # long-lead parts: one order for a quarter
    break_price_band: tuple = (0.5, 1.6)  # quoted break vs unit cost, to trust the row


def demand_rate(demands, today, min_weeks):
    """Booked units per week: everything netted against the part, spread over
    today to the last need (at least `min_weeks`, so a lumpy backlog due next
    month doesn't read as a huge rate)."""
    total = sum(d.qty for d in demands)
    if total <= 0:
        return 0.0
    last = max(d.date for d in demands)
    weeks = max((last - today).days / 7.0, min_weeks)
    return total / weeks


def economic_weeks(rate, unit_cost, policy):
    """The stretch of weeks one order should cover."""
    if rate <= 0:
        return policy.min_cover_weeks
    if unit_cost <= 0:
        return policy.no_cost_weeks
    years = math.sqrt(2 * policy.order_cost / (policy.holding_rate * rate * 52 * unit_cost))
    return min(max(years * 52, policy.min_cover_weeks), policy.max_cover_weeks)


def size_buy(
    part,
    info,
    buys,
    min_qty,
    demands,
    today,
    policy,
    use_min_mult=True,
    committed=False,
    recent_pos=(),
    breaks=(),
):
    """The recommendation for one part.

    buys        the part's planned buys (PlannedOrder), any date
    min_qty     this week's minimum (what rank.buy_list summed)
    recent_pos  [(po, created date, qty, buyer)] open POs for the part
    breaks      [(qty, unit price)] the buy's vendor quotes on Part_Vendor
    """
    buys = sorted(buys, key=lambda o: (o.need_by, o.place_by))
    unit_cost = float(info.unit_cost) if info else 0.0
    rate = demand_rate(demands, today, policy.min_rate_weeks)
    add_to = None
    since = today - timedelta(days=policy.add_to_po_days)
    fresh = [p for p in recent_pos if p[1] and p[1] >= since]
    if fresh:
        po, created, qty, buyer = max(fresh, key=lambda p: p[1])
        add_to = {"po": po, "created": created, "qty": qty, "buyer": buyer}

    base = {
        "min_qty": min_qty,
        "rate_per_week": round(rate, 2),
        "add_to_po": add_to,
    }
    if not buys:
        got, rest = 0.0, []
        for o in buys:
            if got < min_qty - 1e-9:
                got += o.qty
            else:
                rest.append(o)
        return dict(
            base,
            qty=min_qty,
            policy="minimum",
            cover_weeks=None,
            covers_until=None,
            later_qty=round(sum(o.qty for o in rest), 3),
            later_place_by=min((o.place_by for o in rest), default=None),
            included=len(buys) - len(rest),
        )

    if committed:
        weeks = policy.committed_cover_weeks
    else:
        weeks = economic_weeks(rate, unit_cost, policy)
    # the stretch starts when this order lands (or the first need, if later):
    # anything needed before it arrives is in the minimum anyway, and a
    # past-due first need must not eat the window
    start = max(buys[0].need_by, plus_workdays(today, buys[0].lead_days or 0))
    cutoff = start + timedelta(days=round(weeks * 7))
    horizon_place = None
    chosen, short = [], 0.0
    for o in buys:
        in_minimum = sum(x.qty for x in chosen) < min_qty - 1e-9
        if in_minimum or o.need_by <= cutoff:
            # don't let the stretch run past the spend cap (the minimum always goes)
            extra = (short + o.shortfall) * unit_cost - min_qty * unit_cost
            if not in_minimum and unit_cost and extra > policy.max_extra_spend:
                break
            chosen.append(o)
            short += o.shortfall or o.qty
        else:
            break
    qty = _round_order(short, info, use_min_mult) if info else short
    qty = max(qty, min_qty)
    rest = [o for o in buys if o not in chosen]
    # a quoted break the booked orders inside the cover cap will use anyway
    price_break = None
    bq = _next_break(qty, breaks, unit_cost, policy)
    if bq:
        cap = start + timedelta(days=round(policy.max_cover_weeks * 7))
        extra = bq - qty
        booked = sum(o.shortfall or o.qty for o in rest if o.need_by <= cap)
        if booked >= extra - 1e-9 and (bq - min_qty) * unit_cost <= policy.max_extra_spend:
            price_break = {"qty": bq, "from_qty": qty}
            qty, left = bq, extra
            while rest and left > 1e-9 and rest[0].need_by <= cap:
                o = rest.pop(0)
                chosen.append(o)
                left -= o.shortfall or o.qty
    if rest:
        horizon_place = min(o.place_by for o in rest)
    covers_until = chosen[-1].need_by if chosen else None
    if committed:
        label = "committed"
    else:
        label = "economic" if qty > min_qty + 1e-9 else "minimum"
    return dict(
        base,
        qty=qty,
        policy=label,
        cover_weeks=round(weeks, 1),
        covers_until=covers_until,
        later_qty=round(
            max(sum(o.qty for o in buys) - qty, 0.0) if price_break else sum(o.qty for o in rest), 3
        ),
        later_place_by=horizon_place,
        included=len(chosen),
        price_break=price_break,
    )


def _next_break(qty, breaks, unit_cost, policy):
    """The smallest quoted break above qty, if the quote looks like per-each
    pricing at about this part's cost (Part_Vendor rows are kept unevenly:
    some per pack, some years stale)."""
    brs = sorted((float(q), float(p)) for q, p in breaks if q and p and q > 0 and p > 0)
    if len(brs) < 2 or unit_cost <= 0:
        return None
    lo, hi = policy.break_price_band
    if not all(lo <= p / unit_cost <= hi for _q, p in brs):
        return None
    above = [q for q, _p in brs if q > qty + 1e-9]
    return above[0] if above else None


def why_words(rec, unit_cost):
    """One plain sentence for the card and the why panel."""
    p = rec["policy"]
    brk = rec.get("price_break")
    tail = (
        f" Rounded up from {brk['from_qty']:g} to {brk['qty']:g}, a quoted price break with this vendor"
        " — booked orders use the extra; check the quote is current."
        if brk
        else ""
    )
    if p == "committed":
        if rec["qty"] <= rec["min_qty"] + 1e-9:
            return (
                f"Long-lead part — this covers what booked orders need; nothing else is due within "
                f"{rec['cover_weeks']:g} weeks." + tail
            )
        return (
            f"Long-lead part with no blanket PO in MAX — one order for about {rec['cover_weeks']:g} weeks "
            "of booked orders, not a new slice every few days." + tail
        )
    if p == "minimum" and rec.get("cover_weeks") is not None:
        if unit_cost >= 1000:
            return "Expensive part — buy only what booked orders need now; it's cheaper to place again than to carry it."
        return "This covers what booked orders need; nothing else is due soon enough to add."
    if p == "minimum":
        return "This covers what booked orders need right now."
    extra = rec["qty"] - rec["min_qty"]
    return (
        f"One order for about {rec['cover_weeks']:g} weeks of booked orders instead of a new PO every week "
        f"— {extra:g} more than the bare minimum"
        + (f", about ${extra * unit_cost:,.0f} of stock" if unit_cost else "")
        + "."
        + tail
    )


def size_all(
    buys, planned, demands, parts, open_pos, committed, settings, today, policy=None, breaks=None
):
    """Add the recommendation to every buy dict in place (qty becomes the
    recommended quantity; min_qty keeps this week's minimum).

    breaks  {(part, vendor name): [(qty, unit price)]} quoted on Part_Vendor
    """
    breaks = breaks or {}
    policy = policy or OrderPolicy()
    by_part = {}
    for o in planned:
        if o.kind == "buy":
            by_part.setdefault(o.part, []).append(o)
    recent = {}
    for r in open_pos.itertuples(index=False):
        created = r.created.date() if hasattr(r.created, "date") else r.created
        if created is None or created != created:
            continue
        recent.setdefault(r.part, []).append((r.po, created, float(r.qty_due), r.buyer))
    for b in buys:
        part = b["part"]
        info = parts.get(part)
        rec = size_buy(
            part,
            info,
            by_part.get(part, []),
            b["qty"],
            demands.get(part, []),
            today,
            policy,
            use_min_mult=settings.use_min_mult_qty,
            committed=part in committed,
            recent_pos=recent.get(part, ()),
            breaks=breaks.get((part, b.get("vendor") or ""), ()),
        )
        unit_cost = b.get("unit_cost") or 0.0
        b["min_qty"] = b["qty"]
        b["min_spend"] = b["spend"]
        b["qty"] = rec["qty"]
        b["spend"] = round(rec["qty"] * unit_cost, 2)
        if b.get("pack_qty"):
            n = rec["qty"] / b["pack_qty"]
            b["packs"] = round(n) if abs(n - round(n)) < 1e-6 else None
        b["sizing"] = dict(rec, why=why_words(rec, unit_cost))
    return buys
