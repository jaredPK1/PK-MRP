"""core/supersede.py: plan the replacement wherever the old part is still named."""

from datetime import date

from pkmrp.core.netting import Demand, Part, Peg, Receipt, plan
from pkmrp.core.settings import PlanSettings
from pkmrp.core.supersede import apply, resolve

TODAY = date(2026, 10, 28)
PEG = (Peg("so", "SO 1/01", "SYS", ("SYS",), 1000.0),)

# 00-2930-00G (obsolete station interface) -> 00-2930-01G; its support
# 64-2694-02G -> 64-2694-03G.
OLD_SI, NEW_SI, OLD_SUP, NEW_SUP = "00-2930-00G", "00-2930-01G", "64-2694-02G", "64-2694-03G"


def test_resolve_follows_chains_and_drops_cycles():
    rules = {"A": {"part": "B"}, "B": {"part": "C", "use_up": True}, "X": {"part": "Y"},
             "Y": {"part": "X"}}
    assert resolve(rules) == {"A": ("C", False), "B": ("C", True)}


def test_orders_on_the_old_parent_buy_the_new_component():
    parts = {
        OLD_SI: Part(OLD_SI, "A", mfg_lt=5),
        NEW_SI: Part(NEW_SI, "A", mfg_lt=5),
        OLD_SUP: Part(OLD_SUP, "B", purchase_lt=25),
        NEW_SUP: Part(NEW_SUP, "B", purchase_lt=25),
    }
    children = {OLD_SI: [(OLD_SUP, 1.0)], NEW_SI: [(NEW_SUP, 1.0)]}
    demands = [Demand(OLD_SI, date(2027, 2, 1), 100, PEG, "so")]
    stock = {OLD_SUP: 56, NEW_SUP: 81, OLD_SI: 6}
    s = PlanSettings()

    before = plan(parts, children, demands, stock, [], s, TODAY)
    assert {o.part for o in before.planned if o.kind == "buy"} == {OLD_SUP}

    rules = {OLD_SI: {"part": NEW_SI, "use_up": True}, OLD_SUP: {"part": NEW_SUP}}
    d2, c2, st2, r2, moved = apply(rules, demands, children, stock, [])
    after = plan(parts, c2, d2, st2, r2, s, TODAY)
    buys = {o.part: o.qty for o in after.planned if o.kind == "buy"}
    assert set(buys) == {NEW_SUP}
    assert buys[NEW_SUP] == 100 - 6 - 81  # old SI stock used up; old support stays put
    assert st2[OLD_SUP] == 56 and OLD_SI not in st2
    assert moved[OLD_SI]["demand"] == 100 and moved[OLD_SI]["stock"] == 6


def test_bom_edges_and_receipts_move_only_with_use_up():
    children = {"PARENT": [("OLD", 2.0), ("NEW", 1.0)]}
    receipts = [Receipt("OLD", date(2026, 12, 1), 10, "po", "PO 1/01/01")]
    _, c, st, r, moved = apply({"OLD": {"part": "NEW"}}, [], children, {"OLD": 5}, receipts)
    assert c == {"PARENT": [("NEW", 3.0)]} and moved["OLD"]["parents"] == 1
    assert st == {"OLD": 5} and r[0].part == "OLD"  # not use-up: shows as overbuy
    _, _, st, r, _ = apply({"OLD": {"part": "NEW", "use_up": True}}, [], {}, {"OLD": 5}, receipts)
    assert st == {"NEW": 5} and r[0].part == "NEW"


def test_no_rules_changes_nothing():
    d = [Demand("A", TODAY, 1, PEG, "so")]
    assert apply({}, d, {"P": [("A", 1)]}, {"A": 1}, []) == (d, {"P": [("A", 1)]}, {"A": 1}, [], {})
