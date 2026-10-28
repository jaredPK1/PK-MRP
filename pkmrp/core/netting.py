"""Time-phased netting: demand against supply, level by level.

Pure: plain data in, plain data out. Parts are processed in low-level-code
order, so a make part's planned orders are exploded into component demand
before those components are netted -- the multi-level backlog explosion and
the netting are one pass.

Per part, demands are taken in date order and covered from, in turn:
  1. on hand (nettable stock);
  2. open receipts (PO lines, open WOs), earliest due first -- a receipt due
     after the demand it covers is an `expedite_open_po` exception;
  3. surplus from an earlier planned order rounded up by MAX's min/mult;
  4. a new planned order, need-by = the demand's date.
Receipts left unused are `cancel_candidate`s; receipts first needed long
after they land are `push_out_open_po`s. A planned buy whose place-by date
(need-by less lead time) has passed is `late_to_place`.

Every planned order and exception carries `pegs` -- the sales-order lines
(or WO requirements) it exists for -- and every part keeps a `ledger` of
the events that produced its numbers: the `why` trace.
"""

import heapq
import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

from .bom import low_level_codes, without_edges
from .calendar import minus_workdays

MAX_PEGS = 50


@dataclass(frozen=True)
class Part:
    part: str
    type: str
    description: str = ""
    purchase_lt: float = 0.0  # business days (PURLT_01)
    mfg_lt: float = 0.0  # working days (MFGLT_01)
    min_qty: float = 0.0
    mult_qty: float = 0.0
    unit_cost: float = 0.0
    buyer: str = ""
    yield_pct: float = 0.0  # YIELD_01; 0 = not set


@dataclass(frozen=True)
class Peg:
    """What a quantity exists for: a sales-order line or a WO requirement."""

    kind: str  # "so" | "wo_req"
    ref: str  # "SO 20047846/03" | "WO 50081234"
    root_part: str  # the part on that SO line / the WO's parent
    path: tuple = ()  # BOM path from root_part down to this part
    value: float = 0.0  # $ of the SO line (0 when unpriced)


@dataclass
class Demand:
    part: str
    date: date
    qty: float
    pegs: tuple
    source: str  # "so" | "wo_req" | "planned_make"


@dataclass(frozen=True)
class Receipt:
    part: str
    date: date
    qty: float
    kind: str  # "po" | "wo"
    ref: str  # "PO 70110162/01/00" | "WO 50081234"


@dataclass
class PlannedOrder:
    part: str
    kind: str  # "buy" | "make"
    qty: float
    need_by: date
    place_by: date  # buy: order by; make: start by
    lead_days: float
    lead_source: str
    pegs: tuple
    late: bool = False
    shortfall: float = 0.0  # the uncovered quantity, before min/mult


@dataclass
class Exception_:
    part: str
    kind: str
    ref: str = ""
    days: int = 0
    qty: float = 0.0
    detail: str = ""
    pegs: tuple = ()


@dataclass
class PlanResult:
    planned: list = field(default_factory=list)
    exceptions: list = field(default_factory=list)
    ledger: dict = field(default_factory=lambda: defaultdict(list))
    levels: dict = field(default_factory=dict)
    cycle_edges: list = field(default_factory=list)
    committed: set | None = None
    # every demand netted against each part, kept whole for the why story
    demands: dict = field(default_factory=lambda: defaultdict(list))


def _round_order(short, part, use_min_mult):
    q = short
    if use_min_mult:
        if part.min_qty and q < part.min_qty:
            q = part.min_qty
        if part.mult_qty and part.mult_qty > 0:
            q = math.ceil(q / part.mult_qty - 1e-9) * part.mult_qty
    return q


def _merge_pegs(pegs_iter):
    seen, out = set(), []
    for pegs in pegs_iter:
        for p in pegs:
            key = (p.kind, p.ref, p.path)
            if key not in seen:
                seen.add(key)
                out.append(p)
                if len(out) >= MAX_PEGS:
                    return tuple(out)
    return tuple(out)


def plan(
    parts, children, demands, on_hand, receipts, settings, today, lead_times=None, committed=None
):
    """Net everything. Arguments:

    parts       {part: Part}
    children    {parent: [(component, qty_per)]}  (already filtered by type code)
    demands     [Demand]  independent demand: backlog lines and WO requirements
    on_hand     {part: qty}  nettable stock
    receipts    [Receipt]  open POs and open WOs
    lead_times  {part: (days, source)}  realized; falls back to PURLT_01
    """
    lead_times = lead_times or {}
    result = PlanResult()
    result.committed = committed
    levels, dropped = low_level_codes(children)
    kids = without_edges(children, dropped)
    result.levels, result.cycle_edges = levels, dropped
    for p, c in dropped:
        result.exceptions.append(
            Exception_(p, "bom_cycle", detail=f"{p} -> {c} closes a loop; edge ignored")
        )

    by_part = defaultdict(list)
    for d in demands:
        by_part[d.part].append(d)
    rec_by_part = defaultdict(list)
    for r in receipts:
        rec_by_part[r.part].append(r)

    # Lowest level first; components reached only through explosion join the
    # heap as their parents plan. A part is netted once, after every parent.
    heap = [(levels.get(p, 0), p) for p in set(by_part) | set(rec_by_part)]
    heapq.heapify(heap)
    done = set()

    while heap:
        _, part = heapq.heappop(heap)
        if part in done:
            continue
        done.add(part)
        new_demand = _net_part(
            part,
            parts,
            kids,
            by_part[part],
            on_hand.get(part, 0.0),
            rec_by_part[part],
            settings,
            today,
            lead_times,
            result,
        )
        for d in new_demand:
            by_part[d.part].append(d)
            if d.part not in done:
                heapq.heappush(heap, (levels.get(d.part, 0), d.part))
            else:  # a cycle that slipped through: never loop
                result.exceptions.append(
                    Exception_(d.part, "late_explosion", detail=f"demand from {part} after netting")
                )
    return result


def _net_part(part, parts, kids, demands, on_hand, receipts, settings, today, lead_times, result):
    """Net one part. Returns component demand created by its planned makes."""
    ledger = result.ledger[part]
    if any(part.startswith(p) for p in settings.doc_prefixes):
        return []
    info = parts.get(part)
    if info is None:
        if demands:
            result.exceptions.append(
                Exception_(
                    part,
                    "unknown_part",
                    detail="not in Part_Master",
                    pegs=_merge_pegs(d.pegs for d in demands),
                )
            )
        return []

    demands = sorted(demands, key=lambda d: (d.date, d.source, d.qty))
    result.demands[part] = demands
    recs = sorted(receipts, key=lambda r: (r.date, r.ref))
    left = [r.qty for r in recs]  # unconsumed qty per receipt
    first_use = [None] * len(recs)
    stock = float(on_hand)
    surplus = 0.0  # from min/mult rounding of earlier planned orders
    ledger.append((None, stock, "on_hand", "nettable stock"))
    for r in recs:
        ledger.append((r.date, r.qty, r.kind, r.ref))

    shortages = []  # (demand, short qty)
    expedite = {}  # receipt index -> earliest need, qty needed before it lands
    for d in demands:
        need = d.qty
        ledger.append((d.date, -d.qty, d.source, ", ".join(p.ref for p in d.pegs[:3])))
        take = min(stock, need)
        stock -= take
        need -= take
        for i, r in enumerate(recs):
            if need <= 1e-9:
                break
            if left[i] <= 1e-9:
                continue
            take = min(left[i], need)
            left[i] -= take
            need -= take
            if first_use[i] is None:
                first_use[i] = d.date
            if r.date > d.date:
                # One expedite per receipt: the earliest need, the qty pulled in.
                x = expedite.get(i)
                if x is None:
                    expedite[i] = {"need": d.date, "qty": take, "pegs": [d.pegs]}
                else:
                    x["qty"] += take
                    x["pegs"].append(d.pegs)
        if need > 1e-9 and surplus > 1e-9:
            take = min(surplus, need)
            surplus -= take
            need -= take
        if need > 1e-9:
            planned_qty = _round_order(need, info, settings.use_min_mult_qty)
            surplus += planned_qty - need
            shortages.append((d, need, planned_qty))

    for i, x in sorted(expedite.items()):
        r = recs[i]
        result.exceptions.append(
            Exception_(
                part,
                "expedite_open_po" if r.kind == "po" else "expedite_open_wo",
                ref=r.ref,
                days=(r.date - x["need"]).days,
                qty=x["qty"],
                detail=f"due {r.date}, {x['qty']:g} needed from {x['need']}",
                pegs=_merge_pegs(x["pegs"]),
            )
        )
    if result.committed is not None:  # segmentation ran: it decides
        long_lead = part in result.committed
    elif info.type in settings.buy_types:
        long_lead = lead_times.get(part, (info.purchase_lt, ""))[0] >= settings.committed_lead_bdays
    else:
        long_lead = info.mfg_lt >= settings.committed_lead_bdays
    for i, r in enumerate(recs):
        if first_use[i] is None and left[i] >= r.qty - 1e-9 and long_lead:
            result.exceptions.append(
                Exception_(
                    part,
                    "beyond_backlog",
                    ref=r.ref,
                    qty=r.qty,
                    detail=f"due {r.date}; long-lead part, covers demand past the backlog",
                )
            )
        elif first_use[i] is None and left[i] >= r.qty - 1e-9:
            result.exceptions.append(
                Exception_(
                    part,
                    "cancel_candidate",
                    ref=r.ref,
                    qty=r.qty,
                    detail=f"due {r.date}; no demand nets against it",
                )
            )
        elif first_use[i] is not None and (first_use[i] - r.date).days > settings.push_out_days:
            result.exceptions.append(
                Exception_(
                    part,
                    "push_out_open_po" if r.kind == "po" else "push_out_open_wo",
                    ref=r.ref,
                    days=(first_use[i] - r.date).days,
                    qty=r.qty,
                    detail=f"due {r.date}, first needed {first_use[i]}",
                )
            )
        if first_use[i] is not None and left[i] > 1e-9 and not long_lead:
            # Part of this receipt is needed; the rest no booked order nets against.
            result.exceptions.append(
                Exception_(
                    part,
                    "excess_on_po" if r.kind == "po" else "excess_on_wo",
                    ref=r.ref,
                    qty=left[i],
                    detail=f"due {r.date}; {r.qty - left[i]:g} of {r.qty:g} needed",
                )
            )

    if not shortages:
        return []

    is_make = info.type in settings.make_types
    is_buy = info.type in settings.buy_types
    if not (is_make or is_buy):
        total = sum(s for _, s, _ in shortages)
        result.exceptions.append(
            Exception_(
                part,
                "short_unplanned_type",
                qty=total,
                detail=f"TYPE_01 '{info.type}' is not planned; short {total:g}",
                pegs=_merge_pegs(d.pegs for d, _, _ in shortages),
            )
        )
        return []

    new_demand = []
    bom = kids.get(part, [])
    if is_make and not bom:
        result.exceptions.append(
            Exception_(
                part,
                "make_without_bom",
                qty=sum(s for _, s, _ in shortages),
                detail="make part with no BOM: can't explode, can't plan its parts",
                pegs=_merge_pegs(d.pegs for d, _, _ in shortages),
            )
        )
    for d, short, qty in shortages:
        if is_make:
            lead, source = info.mfg_lt, "MFGLT_01"
        else:
            lead, source = lead_times.get(part, (info.purchase_lt, "PURLT_01"))
        place_by = minus_workdays(d.date, lead)
        order = PlannedOrder(
            part,
            "make" if is_make else "buy",
            qty,
            d.date,
            place_by,
            lead,
            source,
            d.pegs,
            late=place_by < today,
            shortfall=short,
        )
        result.planned.append(order)
        ledger.append((d.date, qty, "planned_" + order.kind, f"place by {place_by}"))
        if order.late and not is_make:
            result.exceptions.append(
                Exception_(
                    part,
                    "late_to_place",
                    days=(today - place_by).days,
                    qty=qty,
                    detail=f"place-by {place_by} for need {d.date}",
                    pegs=d.pegs,
                )
            )
        # A make explodes its BOM at its start date; a buy explodes only the
        # kit PK consigns to the vendor (`children` holds just those
        # components for bought parents), due there when the PO is placed.
        for comp, qpu in bom:
            pegs = tuple(Peg(p.kind, p.ref, p.root_part, p.path + (comp,), p.value) for p in d.pegs)
            source = "planned_make" if is_make else "planned_kit"
            new_demand.append(Demand(comp, place_by, qty * qpu, pegs, source))
    return new_demand
