"""Which components PK supplies to the vendors that build its bought
assemblies (contract-manufactured boards, subcontract and outside work).

MAX keeps a full BOM on a bought assembly -- the CM's parts list -- but PK
supplies only a few of those parts, typically the expensive or hard-to-find
ones (the 31-7100-01SG FPGA on the 8000 boards). Exploding the whole BOM
would invent thousands of buys; exploding none hides those parts (the FPGA
read as 290 units of cancel candidates with no demand at all).

So the list is learned from what PK actually did: a (parent, component) pair
is consigned when, in the evidence window, PK
  * issued or transferred the component citing a PO for that parent
    (Chad's OFFSITE @ vendor moves, REFDES = the PO number), or
  * carried it as a requirement on a subcontract PO for that parent,
and the pair is on the parent's BOM (any type code -- most CM BOM rows are
TYPCDE_02 'E'). Measured 2026-10-28 over 24 months: 115 pairs, 67 parents,
87 components -- under 1% of bought-assembly BOM rows.

A kit belongs to the vendors PK sent it to, not to the part: 62-3206-00G's
unfinished blank went to KJS on a subcontract PO, but the finished part is
now bought complete from Duyck, and a Duyck PO needs no blank. So kit demand
applies only to POs (and planned buys) with a vendor in the pair's evidence.
"""

from collections import defaultdict

from .calendar import as_date, minus_workdays
from .netting import Demand, Peg


def consigned_edges(moves, po_parts, sub_reqs, bom):
    """({parent: [(component, qty_per)]}, {(parent, component): evidence}).

    moves     consign_moves frame (component, po, moved)
    po_parts  po_parts frame (po, parent)
    sub_reqs  subcontract_reqs frame (parent, part)
    bom       bom frame, every type code (parent, component, qty_per, type_code)
    """
    parent_of = defaultdict(set)
    vendor_of_po = {}
    for r in po_parts.itertuples(index=False):
        parent_of[r.po].add(r.parent)
        if getattr(r, "vendor_id", ""):
            vendor_of_po[r.po] = r.vendor_id
    qty = {
        (r.parent, r.component): (float(r.qty_per), r.type_code)
        for r in bom.itertuples(index=False)
    }

    evidence = defaultdict(lambda: {"moves": 0, "sub_reqs": 0, "last": None, "vendors": set()})
    for r in moves.itertuples(index=False):
        for parent in parent_of.get(r.po, ()):
            key = (parent, r.component)
            if key in qty:
                e = evidence[key]
                e["moves"] += 1
                if r.po in vendor_of_po:
                    e["vendors"].add(vendor_of_po[r.po])
                d = as_date(r.moved)
                if d and (e["last"] is None or d > e["last"]):
                    e["last"] = d
    for r in sub_reqs.itertuples(index=False):
        key = (r.parent, r.part)
        if key in qty:
            evidence[key]["sub_reqs"] += 1
            po = getattr(r, "po", None)
            if po in vendor_of_po:
                evidence[key]["vendors"].add(vendor_of_po[po])

    children = defaultdict(list)
    for (parent, comp), ev in sorted(evidence.items()):
        q, tc = qty[(parent, comp)]
        ev["type_code"] = tc
        ev["vendors"] = sorted(ev["vendors"])
        children[parent].append((comp, q))
    return dict(children), dict(evidence)


def kit_vendors(evidence):
    """{(parent, component): {vendor_id}} -- empty set means no vendor known."""
    return {k: set(v.get("vendors") or ()) for k, v in evidence.items()}


def kit_for(parent, kit, vendor, vendors):
    """The part of `kit` PK sends to `vendor`. A pair with no known vendor is
    kept (older evidence); one whose vendors don't include `vendor` is not."""
    return [
        (comp, q)
        for comp, q in kit
        if not vendors.get((parent, comp)) or vendor in vendors[(parent, comp)]
    ]


def open_kit_demand(open_pos, consigned, sub_open_lines, lead_of, today, vendors=None):
    """Consigned components still owed to vendors for open assembly POs.

    For each open PO line of a parent with a consigned kit, the kit is due at
    the vendor a lead time before the line is due. Lines that are MAX-native
    subcontract POs are skipped: their own requirement rows are the demand
    (subcontract_demand), and counting both would double it. Stock already
    sitting at the vendor (OFFSITE @ locations are nettable) covers it.
    """
    out = []
    for r in open_pos.itertuples(index=False):
        kit = consigned.get(r.part)
        if not kit or (r.po, r.line) in sub_open_lines or (r.qty_due or 0) <= 0:
            continue
        due = as_date(r.cur_due) or today
        need = minus_workdays(due, lead_of(r.part))
        for comp, qpu in kit_for(r.part, kit, getattr(r, "vendor_id", ""), vendors or {}):
            peg = Peg("po_kit", f"PO {r.po}/{r.line}", r.part, (r.part, comp))
            out.append(Demand(comp, need, float(r.qty_due) * qpu, (peg,), "po_kit"))
    return out


def subcontract_demand(sub_reqs, today):
    """(demands, {(po, line)}) from open requirement rows on open subcontract POs."""
    out, lines = [], set()
    for r in sub_reqs.itertuples(index=False):
        if r.status != "3" or (r.qty_open or 0) <= 0:
            continue
        lines.add((r.po, r.line))
        peg = Peg("sub_req", f"PO {r.po}/{r.line}", r.parent, (r.parent, r.part))
        out.append(Demand(r.part, as_date(r.due) or today, float(r.qty_open), (peg,), "sub_req"))
    return out, lines
