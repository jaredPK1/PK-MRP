"""core/atp.py: earliest date material supports, and what binds it."""

from datetime import date

from pkmrp.core.atp import earliest_cover, promise, timelines
from pkmrp.core.calendar import plus_workdays
from pkmrp.core.netting import Part

TODAY = date(2026, 10, 28)
D = date


def test_earliest_cover_respects_booked_orders():
    # 5 on hand, an order takes 5 on 11-10, a PO brings 10 on 12-01
    tl = (5.0, [(D(2026, 11, 10), -5.0), (D(2026, 12, 1), 10.0)])
    assert earliest_cover(tl, 3, TODAY) == D(2026, 12, 1)  # taking 3 now would starve 11-10
    assert earliest_cover(tl, 10, TODAY) == D(2026, 12, 1)
    assert earliest_cover(tl, 11, TODAY) is None
    assert earliest_cover((5.0, []), 5, TODAY) == TODAY


def test_timelines_keep_firm_supply_and_demand_not_planned_orders():
    ledger = {
        "L": [
            (None, 4.0, "on_hand", ""),
            (D(2026, 12, 1), 10.0, "po", "PO 1"),
            (D(2026, 11, 1), -3.0, "so", "SO 1"),
            (D(2026, 12, 5), 7.0, "planned_buy", ""),
        ]
    }
    assert timelines(ledger)["L"] == (4.0, [(D(2026, 11, 1), -3.0), (D(2026, 12, 1), 10.0)])


def test_promise_builds_through_the_bom_and_names_the_binding_part():
    parts = {
        "SYS": Part("SYS", "A", mfg_lt=10),
        "LENS": Part("LENS", "B", purchase_lt=100),
        "SCREW": Part("SCREW", "B", purchase_lt=5),
    }
    children = {"SYS": [("LENS", 1.0), ("SCREW", 4.0)]}
    lines = {"LENS": (0.0, [(D(2027, 1, 28), 20.0)]), "SCREW": (100.0, [])}
    r = promise(
        "SYS", 2, D(2026, 12, 15), children, lines, parts, lambda p: parts[p].purchase_lt, TODAY
    )
    assert r["binding"] == "LENS" and r["path"] == ("SYS", "LENS")
    assert r["date"] == plus_workdays(D(2027, 1, 28), 10)
    assert r["days_late"] == (r["date"] - D(2026, 12, 15)).days


def test_stock_on_the_part_itself_answers_today():
    parts = {"KIT": Part("KIT", "A", mfg_lt=3)}
    r = promise("KIT", 1, D(2026, 11, 1), {}, {"KIT": (2.0, [])}, parts, lambda p: 0, TODAY)
    assert r["date"] == TODAY and r["days_late"] == 0 and r["binding"] == "KIT"


def test_no_supply_means_a_new_buy_at_its_lead_time():
    parts = {"FPGA": Part("FPGA", "B", purchase_lt=370)}
    r = promise("FPGA", 5, None, {}, {}, parts, lambda p: 370, TODAY)
    assert r["date"] == plus_workdays(TODAY, 370) and r["steps"][0]["how"].startswith("new buy")


def test_short_for_booked_orders_means_buy_fresh_not_wait_for_the_horizon():
    # The lens is already short: booked orders take more than is coming.
    # Waiting would mean "never"; a new buy placed today wins.
    parts = {"LENS": Part("LENS", "B", purchase_lt=20)}
    lines = {"LENS": (0.0, [(D(2026, 11, 1), -30.0), (D(2027, 6, 1), 20.0)])}
    r = promise("LENS", 1, None, {}, lines, parts, lambda p: 20, TODAY)
    assert r["date"] == plus_workdays(TODAY, 20) and r["steps"][0]["how"].startswith("new buy")


def test_on_order_beats_a_fresh_buy_when_it_lands_sooner():
    parts = {"LENS": Part("LENS", "B", purchase_lt=100)}
    lines = {"LENS": (0.0, [(D(2026, 12, 1), 10.0)])}
    r = promise("LENS", 5, None, {}, lines, parts, lambda p: 100, TODAY)
    assert r["date"] == D(2026, 12, 1) and r["steps"][0]["how"].startswith("on order")
