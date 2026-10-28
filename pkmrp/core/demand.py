"""Independent demand: open backlog lines and open WO requirements.

Backlog lines that can't be placed in time go to worklists instead of the
plan, so nothing disappears silently:
  * unscheduled -- due in settings.unscheduled_from_year or later (the
    2032-34 placeholder dates);
  * no_date     -- no usable due date at all;
  * unplannable -- a make part with no BOM and nothing on hand.
"""

from .calendar import as_date
from .netting import Demand, Peg


def backlog_demand(so_lines, settings, has_bom, on_hand, part_types):
    """(demands, worklists) from an open_so_lines frame."""
    demands = []
    work = {"unscheduled": [], "no_date": [], "unplannable": []}
    for r in so_lines.itertuples(index=False):
        due = as_date(getattr(r, settings.demand_date, None)) or as_date(r.cur_due)
        qty = float(r.qty_due or 0)
        if qty <= 0:
            continue
        price = float(r.unit_price or 0) if r.unit_price == r.unit_price else 0.0
        line = {
            "so": r.so,
            "line": r.line,
            "part": r.part,
            "qty": qty,
            "due": due,
            "customer": r.customer,
            "value": round(price * qty, 2),
        }
        if due is None:
            work["no_date"].append(line)
            continue
        if due.year >= settings.unscheduled_from_year:
            work["unscheduled"].append(line)
            continue
        if (
            part_types.get(r.part) in settings.make_types
            and r.part not in has_bom
            and on_hand.get(r.part, 0) <= 0
        ):
            work["unplannable"].append(line)
        peg = Peg("so", f"SO {r.so}/{r.line}", r.part, (r.part,), line["value"])
        demands.append(Demand(r.part, due, qty, (peg,), "so"))
    return demands, work


def wo_requirement_demand(wo_reqs, today):
    """Components still owed to open work orders. Past-due ones are needed now."""
    out = []
    for r in wo_reqs.itertuples(index=False):
        qty = float(r.qty_open or 0)
        if qty <= 0:
            continue
        due = as_date(r.due) or today
        peg = Peg("wo_req", f"WO {r.wo}", r.parent, (r.parent, r.part))
        out.append(Demand(r.part, due, qty, (peg,), "wo_req"))
    return out
