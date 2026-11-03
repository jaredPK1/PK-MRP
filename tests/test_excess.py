"""Excess stock for the reserve."""

from datetime import date

from pkmrp.core.excess import excess
from pkmrp.core.netting import Demand, Part
from pkmrp.core.settings import PlanSettings

S = PlanSettings()
D = date(2027, 1, 1)


def part(p, t="B", cost=10.0):
    return Part(p, t, description=p, unit_cost=cost)


def dem(p, q):
    return Demand(p, D, q, (), "so")


def run(stock, parts, demands=None, segments=(), plans=(), usage=None, floor=None):
    return excess(demands or {}, stock, parts, list(segments), list(plans), usage or {}, S, floor)


def test_bought_part_beyond_booked_demand():
    out = run({"B1": 10}, {"B1": part("B1")}, {"B1": [dem("B1", 4)]})
    r = out["rows"][0]
    assert (r["extra"], r["value"], r["kind"], r["basis"], r["tier"]) == (6, 60.0, "bought", "booked", "over")


def test_made_part_counts_and_covered_part_is_left_out():
    parts = {"A1": part("A1", "A", 100.0), "B1": part("B1")}
    out = run({"A1": 2, "B1": 3}, parts, {"B1": [dem("B1", 3)]})
    assert [r["part"] for r in out["rows"]] == ["A1"]
    assert out["rows"][0]["kind"] == "made"
    assert out["totals"]["by_kind"] == {"made": 200.0}


def test_long_lead_measured_against_12_month_plan():
    plans = [{"part": "L1", "requirement_12m": 20, "buffer": 5}]
    seg = [{"part": "L1", "segment": "committed"}]
    out = run({"L1": 30}, {"L1": part("L1")}, {"L1": [dem("L1", 2)]}, seg, plans)
    r = out["rows"][0]
    assert (r["needed"], r["extra"], r["basis"], r["long_lead"]) == (25, 5, "12-month plan", True)


def test_safety_floor_is_not_excess():
    out = run({"B1": 10}, {"B1": part("B1")}, floor={"B1": 10})
    assert out["rows"] == []


def test_tiers_by_use():
    parts = {p: part(p) for p in ("D", "I", "S")}
    usage = {"I": (0.0, 5.0, None), "S": (12.0, 0.0, date(2026, 9, 1))}
    out = run({"D": 1, "I": 1, "S": 1}, parts, usage=usage)
    tiers = {r["part"]: r["tier"] for r in out["rows"]}
    assert tiers == {"D": "dead", "I": "idle", "S": "slow"}
    s = next(r for r in out["rows"] if r["part"] == "S")
    assert s["months_of_use"] == 1.0


def test_bulk_docs_and_uncosted_left_out():
    parts = {"Y1": part("Y1", "Y"), "97-0001": part("97-0001"), "Z": part("Z", cost=0.0)}
    assert run({"Y1": 5, "97-0001": 5, "Z": 5}, parts)["rows"] == []
