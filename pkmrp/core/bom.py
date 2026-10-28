"""Bill-of-materials structure: children, where-used, low-level codes.

A BOM in MAX can contain a cycle (a part that, through some path, contains
itself). Explosion would never end, so low_level_codes() finds cycles,
reports every edge it had to ignore, and plans as if those edges were not
there. A cycle is a data error for engineering, not something to plan
around silently -- the edges come back on the worklist.
"""

from collections import defaultdict


def children_map(edges):
    """{parent: [(component, qty_per), ...]} from (parent, component, qty_per)
    tuples. Duplicate pairs are summed (MAX shouldn't have them after the
    latest-effective filter, but a summed duplicate is safer than a dropped one)."""
    acc = defaultdict(float)
    for parent, comp, qty in edges:
        if parent and comp and qty and qty > 0:
            acc[(parent, comp)] += float(qty)
    out = defaultdict(list)
    for (parent, comp), qty in sorted(acc.items()):
        out[parent].append((comp, qty))
    return dict(out)


def where_used(children):
    """{component: [(parent, qty_per), ...]}."""
    out = defaultdict(list)
    for parent, kids in children.items():
        for comp, qty in kids:
            out[comp].append((parent, qty))
    return dict(out)


def low_level_codes(children):
    """({part: level}, [cycle edges dropped]).

    Level 0 = never a component; a part's level is one more than the deepest
    parent that uses it, so processing parts in ascending level guarantees
    every parent's planned orders exist before its components are netted.
    Iterative DFS, so deep BOMs can't hit Python's recursion limit.
    """
    WHITE, GREY, BLACK = 0, 1, 2
    colour = defaultdict(int)
    dropped = []
    order = []  # post-order: components before parents

    parts = set(children)
    for kids in children.values():
        parts.update(c for c, _ in kids)

    for root in sorted(parts):
        if colour[root] != WHITE:
            continue
        stack = [(root, iter(children.get(root, ())))]
        colour[root] = GREY
        while stack:
            node, it = stack[-1]
            nxt = next(it, None)
            if nxt is None:
                colour[node] = BLACK
                order.append(node)
                stack.pop()
                continue
            comp = nxt[0]
            if colour[comp] == GREY:  # back edge: a cycle
                dropped.append((node, comp))
            elif colour[comp] == WHITE:
                colour[comp] = GREY
                stack.append((comp, iter(children.get(comp, ()))))

    dropped_set = set(dropped)
    level = {p: 0 for p in parts}
    for node in reversed(order):  # parents before components
        for comp, _ in children.get(node, ()):
            if (node, comp) not in dropped_set:
                level[comp] = max(level[comp], level[node] + 1)
    return level, dropped


def without_edges(children, dropped):
    """children with the dropped (cycle) edges removed."""
    drop = set(dropped)
    return {p: [(c, q) for c, q in kids if (p, c) not in drop] for p, kids in children.items()}
