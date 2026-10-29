"""Replacements: plan the new part wherever an old one is still called for.

Engineering obsoletes a part and releases its replacement, but open orders,
open work orders and BOMs keep naming the old one until someone edits them
in MAX. Planned as written, that buys the dead part and never the new one
(64-2694-02G: 46 orders still on the obsolete station interface 00-2930-00G,
so the plan said "buy -02G" and never asked for -03G).

A replacement rule -- old -> new, set by a planner on the Notes page --
moves, before netting:

  * independent demand (order lines, WO requirements) from old to new;
  * BOM edges: a parent that still lists old gets new instead;
  * with "use up": old's stock and open receipts count as supply of new
    (they are interchangeable); without it they stay on old, where the plan
    shows them as stock nobody needs and POs to cancel.

Chains resolve (A -> B -> C plans C). A rule pointing back on itself is
ignored. Pure.
"""

from dataclasses import replace


def resolve(rules):
    """{old: (final_new, use_up)} following chains; cycles dropped."""
    out = {}
    for old in rules:
        seen, cur, use_up = {old}, old, bool(rules[old].get("use_up"))
        while cur in rules:
            nxt = rules[cur]["part"]
            if nxt in seen:
                cur = None
                break
            seen.add(nxt)
            cur = nxt
        if cur and cur != old:
            out[old] = (cur, use_up)
    return out


def apply(rules, demands, children, on_hand, receipts):
    """(demands, children, on_hand, receipts, moved) with the rules applied.
    `moved` is {old: {"to", "use_up", "demand", "stock", "receipts", "parents"}}."""
    to = resolve(rules)
    if not to:
        return demands, children, on_hand, receipts, {}
    moved = {
        old: {"to": new, "use_up": up, "demand": 0.0, "stock": 0.0, "receipts": 0, "parents": 0}
        for old, (new, up) in to.items()
    }

    new_demands = []
    for d in demands:
        if d.part in to:
            moved[d.part]["demand"] += d.qty
            new_demands.append(replace(d, part=to[d.part][0]))
        else:
            new_demands.append(d)

    new_children = {}
    for parent, kids in children.items():
        acc = {}
        for comp, qty in kids:
            if comp in to:
                moved[comp]["parents"] += 1
                comp = to[comp][0]
            acc[comp] = acc.get(comp, 0.0) + qty
        # a parent that is itself replaced keeps its BOM; nothing explodes it
        new_children[parent] = [(c, q) for c, q in acc.items() if c != parent]

    stock = dict(on_hand)
    new_receipts = []
    for old, (new, up) in to.items():
        if up and stock.get(old):
            moved[old]["stock"] = stock[old]
            stock[new] = stock.get(new, 0.0) + stock.pop(old)
    for r in receipts:
        if r.part in to and to[r.part][1]:
            moved[r.part]["receipts"] += 1
            new_receipts.append(replace(r, part=to[r.part][0]))
        else:
            new_receipts.append(r)
    return new_demands, new_children, stock, new_receipts, moved
