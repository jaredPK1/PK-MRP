"""MAX safety stock: judged (core/safety.py), then netted as a floor."""

from dataclasses import replace
from datetime import date

from pkmrp.core.netting import Demand, Part, Peg, Receipt, plan
from pkmrp.core.rank import buy_list
from pkmrp.core.safety import judge, summary
from pkmrp.core.settings import PlanSettings

TODAY = date(2026, 11, 2)
S = PlanSettings()


def part(p="CUBE", ss=10, lt=20, cost=288.0):
    return Part(p, "B", "50/50 CUBE", purchase_lt=lt, unit_cost=cost, safety_stock=ss)


def so(p, d, q, ref="SO 20048248/01"):
    return Demand(p, d, q, (Peg("so", ref, "02-2920-00G"),), "so")


USED = {"CUBE": (8.0, 4.0, date(2026, 10, 1))}


def test_safety_stock_nets_after_booked_demand_as_a_place_now_buy():
    # 13 on hand, 18 booked -> 5 short for orders, then 10 more for safety stock
    r = plan({"CUBE": part()}, {}, [so("CUBE", date(2027, 2, 12), 18)], {"CUBE": 13}, [], S, TODAY,
             usage=USED)
    by = {o.reason: o for o in r.planned}
    assert by["booked"].qty == 5 and by["booked"].need_by == date(2027, 2, 12)
    assert by["safety_stock"].qty == 10 and by["safety_stock"].place_by == TODAY
    assert not by["safety_stock"].late and not by["safety_stock"].pegs
    assert not [e for e in r.exceptions if e.kind == "late_to_place"]
    assert r.safety["CUBE"]["verdict"] == "trusted"


def test_a_po_held_for_safety_stock_is_not_excess_or_expedited():
    rec = Receipt("CUBE", date(2026, 12, 1), 20, "po", "PO 70110001/01/00")
    r = plan({"CUBE": part(ss=8)}, {}, [so("CUBE", date(2027, 1, 5), 18)], {"CUBE": 11}, [rec], S,
             TODAY, usage=USED)
    assert not r.planned  # 11 + 20 covers 18 booked + 8 safety stock
    excess = [e.qty for e in r.exceptions if e.kind == "excess_on_po"]
    assert excess == [5]  # 13 without safety stock
    assert not [e for e in r.exceptions if e.kind == "expedite_open_po"]


def test_stock_below_safety_stock_with_no_demand_is_still_planned():
    r = plan({"CUBE": part(ss=4)}, {}, [], {"CUBE": 1}, [], S, TODAY, usage=USED)
    assert [(o.reason, o.qty) for o in r.planned] == [("safety_stock", 3)]
    assert "CUBE" not in r.demands  # no booked demand recorded for it


def test_safety_stock_off_or_on_make_parts_plans_nothing_extra():
    off = replace(S, use_safety_stock=False)
    assert not plan({"CUBE": part()}, {}, [], {}, [], off, TODAY, usage=USED).planned
    make = Part("ASSY", "A", "ASSY", mfg_lt=5, safety_stock=5)
    assert not plan({"ASSY": make}, {}, [], {}, [], S, TODAY).planned


def test_judge_ignores_dormant_and_flagged_parts():
    assert judge(1, [], (0, 0, None), TODAY)["why"] == "not used in two years and nothing booked"
    j = judge(1, [], (0, 3, date(2025, 6, 1)), TODAY)
    assert j["verdict"] == "ignored" and j["use"] == 0 and "12 months" in j["why"]
    j = judge(10, [so("CUBE", date(2027, 1, 5), 4)], (8, 0, None), TODAY, flag="on hold (part note)")
    assert j["verdict"] == "ignored" and j["why"] == "on hold (part note)"


def test_judge_caps_at_six_months_of_the_bigger_of_use_and_booked_rate():
    # 300 set, 36 used a year (3/month) -> 18 = 6 months
    j = judge(300, [], (36, 30, date(2026, 10, 1)), TODAY)
    assert j["verdict"] == "capped" and j["use"] == 18 and j["months"] == 100
    # NPI part: little history, but 18 booked over ~3.4 months -> 10 is under 2 months
    j = judge(10, [so("CUBE", date(2027, 2, 12), 18)], (8, 4, None), TODAY)
    assert j["verdict"] == "trusted" and j["use"] == 10


def test_ignored_safety_stock_plans_nothing_and_shows_on_the_summary():
    r = plan({"CUBE": part(ss=6)}, {}, [], {}, [], S, TODAY, usage={},
             no_stock={"CUBE": "replaced by CUBE-2"})
    assert not r.planned and r.safety["CUBE"]["why"] == "replaced by CUBE-2"
    s = summary(r.safety, {"CUBE": part(ss=6)}, [])
    assert s["counts"] == {"trusted": 0, "capped": 0, "ignored": 1}
    assert s["rows"][0]["value_not_held"] == 6 * 288.0


def test_safety_stock_only_buys_rank_after_every_order_buy():
    parts = {"CUBE": part(), "LENS": part("LENS", ss=0, cost=1.0)}
    r = plan(parts, {}, [so("LENS", date(2026, 11, 20), 2)], {"CUBE": 3}, [], S, TODAY,
             usage={"CUBE": (60.0, 50.0, None), "LENS": (5, 0, None)})
    buys = buy_list(r.planned, parts, {}, {}, {}, TODAY, horizon_workdays=20)
    assert [b["part"] for b in buys] == ["LENS", "CUBE"]  # a $0 order buy still beats SS-only
    lens, cube = buys
    assert cube["ss_only"] and cube["ss_qty"] == 7 and not cube["wo_only"]
    assert not lens["ss_only"] and lens["ss_qty"] == 0
