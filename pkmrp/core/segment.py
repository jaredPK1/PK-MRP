"""Order-driven vs committed: which bought parts get 12-month supply.

Short-lead parts are bought purely against booked orders; the few whose own
history proves a long lead get committed 12-month supply. A bought part is

  * `committed`  -- its realized P80 (own receipts, >= 3 lines) is more than
    `committed_p80_days` calendar days (90): booked orders alone don't give
    enough warning;
  * `unproven_long` -- no receipt history of its own, but PURLT_01 says more
    than 90 days. MAX's lead times are too long on about half of parts (52%
    run under 0.75x their setting), so these are checked, not committed;
  * `order_driven` -- everything else.

The single-source rule (single source, P80 > 60 days, gates more than $X of
revenue) is off by default (`single_source_gate=None`): with orders valued
whole -- most lines carry no price -- every part in a $50M multi-system
order "gates" $50M and the rule swept in 405 parts. It needs a revenue-at-
risk measure first.

Measured 2026-10-28 over the parts that gate an open order due within 12
months (2,249): committed 119, against the brief's ~85; the remainder of the
gap is the brief's calendar-day reading of PURLT_01 (it is business days:
65% of PO lines are due exactly PURLT business days after creation).

"Gates" walks the BOM (and consigned kits), not the plan, so a part counts
even when stock covers it today. Thresholds are calendar days (x 7/5).
"""

from collections import defaultdict
from datetime import timedelta

from .calendar import as_date

CAL_PER_BDAY = 7 / 5


def gated_orders(so_lines, children, settings, today):
    """{part: {so,...}} -- the open orders due within 12 months that each part
    feeds, at any BOM depth. Memoized per parent; cycle-safe."""
    horizon = today + timedelta(days=365)
    memo = {}

    def below(part, path):
        if part in memo:
            return memo[part]
        out = set()
        for comp, _ in children.get(part, ()):
            if comp in path:
                continue
            out.add(comp)
            out |= below(comp, path | {comp})
        memo[part] = out
        return out

    gated = defaultdict(set)
    for r in so_lines.itertuples(index=False):
        due = as_date(getattr(r, settings.demand_date, None)) or as_date(r.cur_due)
        if not due or due > horizon or due.year >= settings.unscheduled_from_year:
            continue
        for p in {r.part} | below(r.part, frozenset({r.part})):
            gated[p].add(r.so)
    return gated


def sources(part_vendors, po_history):
    """({part: approved vendor count}, {part: vendors actually bought from})."""
    approved = defaultdict(set)
    for r in part_vendors.itertuples(index=False):
        approved[r.part].add(r.vendor_id)
    used = defaultdict(set)
    for r in po_history.itertuples(index=False):
        if r.vendor_id:
            used[r.part].add(r.vendor_id)
    return approved, used


def classify(parts, lead_stats, approved, used, gated, so_values, settings):
    """[{part, segment, reasons, p50_days, p80_days, ...}] for every bought
    part that gates at least one booked order in the next 12 months."""
    out = []
    for part, orders in gated.items():
        info = parts.get(part)
        if info is None or info.type not in settings.buy_types:
            continue
        lt = lead_stats.get(part)
        if not lt:
            continue
        p50 = round(lt["median"] * CAL_PER_BDAY)
        p80 = round(lt["p80"] * CAL_PER_BDAY)
        n_used, n_approved = len(used.get(part, ())), len(approved.get(part, ()))
        single = max(n_used, n_approved) <= 1
        value = round(sum(so_values.get(so, 0.0) for so in orders), 2)
        proven = lt["source"].startswith("realized")
        reasons, segment = [], "order_driven"
        if proven and p80 > settings.committed_p80_days:
            reasons.append(f"P80 lead {p80} days > {settings.committed_p80_days} (own receipts)")
            segment = "committed"
        elif not proven and p80 > settings.committed_p80_days:
            reasons.append(f"PURLT says {p80} days; no receipt history to prove it")
            segment = "unproven_long"
        if (
            settings.single_source_gate is not None
            and single
            and proven
            and p80 > settings.single_source_days
            and value >= settings.single_source_gate
        ):
            reasons.append(f"single source, {p80}-day lead, gates ${value:,.0f}")
            segment = "committed"
        out.append(
            {
                "part": part,
                "description": info.description,
                "segment": segment,
                "reasons": reasons,
                "p50_days": p50,
                "p80_days": p80,
                "lead_source": lt["source"],
                "lines": lt["lines"],
                "purlt_days": round(info.purchase_lt * CAL_PER_BDAY),
                "single_source": single,
                "vendors_used": n_used,
                "vendors_approved": n_approved,
                "orders": len(orders),
                "gated_value": value,
            }
        )
    order = {"committed": 0, "unproven_long": 1, "order_driven": 2}
    out.sort(key=lambda r: (order[r["segment"]], -r["gated_value"], r["part"]))
    return out
