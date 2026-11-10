from datetime import date, timedelta

import pandas as pd

from pkmrp.core.netting import Demand, Part, PlannedOrder
from pkmrp.core.order_qty import OrderPolicy, economic_weeks, size_all, size_buy, why_words
from pkmrp.core.settings import PlanSettings

TODAY = date(2026, 10, 30)
POL = OrderPolicy()


def _weekly_buys(part, n, qty, start=TODAY + timedelta(days=35)):
    out = []
    for i in range(n):
        need = start + timedelta(days=7 * i)
        out.append(
            PlannedOrder(
                part,
                "buy",
                qty,
                need,
                need - timedelta(days=42),
                30,
                "PURLT_01",
                (),
                late=False,
                shortfall=qty,
            )
        )
    return out


def _demands(part, n, qty, start=TODAY + timedelta(days=35)):
    return [Demand(part, start + timedelta(days=7 * i), qty, (), "so") for i in range(n)]


def test_cheap_steady_part_covers_weeks_not_one_slice():
    # the 35-0126-00G case: $36, ~10 a week, 14 due now
    info = Part("35-0126-00G", "B", "cable", unit_cost=36.0)
    buys = _weekly_buys(info.part, 20, 10)
    rec = size_buy(info.part, info, buys, 10, _demands(info.part, 20, 10), TODAY, POL)
    assert rec["policy"] == "economic"
    assert 6 <= rec["cover_weeks"] <= 12
    assert rec["qty"] >= 60 and rec["qty"] <= 130
    assert rec["later_qty"] == 200 - rec["qty"]


def test_expensive_part_stays_at_the_minimum():
    info = Part("98-0885-00G", "B", "sampling head", unit_cost=42465.0)
    buys = _weekly_buys(info.part, 6, 1)
    rec = size_buy(info.part, info, buys, 1, _demands(info.part, 6, 1), TODAY, POL)
    assert rec["qty"] == 1
    assert rec["policy"] == "minimum"


def test_never_beyond_booked_demand_and_never_below_minimum():
    info = Part("X", "B", "", unit_cost=1.0)
    buys = _weekly_buys("X", 3, 5)
    rec = size_buy("X", info, buys, 5, _demands("X", 3, 5), TODAY, POL)
    assert rec["qty"] == 15  # all booked demand, nothing invented
    assert size_buy("X", info, buys[:1], 5, [], TODAY, POL)["qty"] == 5


def test_spend_cap_and_min_mult_rounding():
    info = Part("Y", "B", "", unit_cost=900.0, mult_qty=4)
    buys = _weekly_buys("Y", 30, 5)
    rec = size_buy(
        "Y", info, buys, 5, _demands("Y", 30, 5), TODAY, OrderPolicy(max_extra_spend=9000)
    )
    assert (rec["qty"] - 5) * 900 <= 9000 + 4 * 900
    assert rec["qty"] % 4 == 0


def test_committed_part_covers_a_quarter_not_a_slice():
    # the Haydon Kerk case: no blanket in MAX, so the minimum came back every few days
    info = Part("Z", "B", "", unit_cost=130.0)
    buys = _weekly_buys("Z", 20, 4)
    rec = size_buy("Z", info, buys, 4, _demands("Z", 20, 4), TODAY, POL, committed=True)
    assert rec["policy"] == "committed"
    assert rec["cover_weeks"] == 13
    # from when the order lands to 13 weeks on: a quarter, not one week's slice
    assert 4 * 13 <= rec["qty"] <= 4 * 16
    assert rec["later_qty"] == 80 - rec["qty"]
    assert "weeks" in why_words(rec, 130.0)


def test_committed_part_respects_spend_cap():
    info = Part("Z", "B", "", unit_cost=5000.0)
    buys = _weekly_buys("Z", 20, 1)
    rec = size_buy("Z", info, buys, 1, _demands("Z", 20, 1), TODAY, POL, committed=True)
    assert (rec["qty"] - 1) * 5000 <= POL.max_extra_spend


def test_rounds_up_to_a_quoted_break_booked_orders_use():
    # 37-0007-01G: 10 at a time, Haydon Kerk quotes 10 / 25
    info = Part("37-0007-01G", "B", "motor", unit_cost=130.53)
    buys = _weekly_buys(info.part, 30, 1)
    breaks = [(1.0, 120.22), (10.0, 114.72), (25.0, 111.36)]
    rec = size_buy(info.part, info, buys, 1, _demands(info.part, 30, 1), TODAY, POL,
                   committed=True, breaks=breaks)
    assert rec["qty"] == 25
    assert rec["price_break"]["qty"] == 25 and rec["price_break"]["from_qty"] < 25
    assert rec["later_qty"] == 30 - 25
    assert "price break" in why_words(rec, 130.53)


def test_no_break_beyond_booked_demand():
    info = Part("B1", "B", "", unit_cost=100.0)
    buys = _weekly_buys("B1", 2, 4)
    rec = size_buy("B1", info, buys, 4, _demands("B1", 2, 4), TODAY, POL,
                   breaks=[(1.0, 100.0), (25.0, 90.0)])
    assert rec["qty"] == 8 and rec["price_break"] is None


def test_break_rows_far_from_cost_are_ignored():
    # per-pack rows: 100x the per-each cost
    info = Part("B2", "B", "", unit_cost=1.0)
    buys = _weekly_buys("B2", 30, 5)
    rec = size_buy("B2", info, buys, 5, _demands("B2", 30, 5), TODAY, POL,
                   breaks=[(1.0, 100.0), (10.0, 95.0), (500.0, 90.0)])
    assert rec["price_break"] is None


def test_recent_po_is_named_to_add_to():
    info = Part("C", "B", "", unit_cost=36.0)
    buys = _weekly_buys("C", 4, 5)
    rec = size_buy(
        "C",
        info,
        buys,
        5,
        _demands("C", 4, 5),
        TODAY,
        POL,
        recent_pos=[
            ("70111303", TODAY - timedelta(days=1), 14.0, "RM"),
            ("70100000", TODAY - timedelta(days=90), 3.0, "AS"),
        ],
    )
    assert rec["add_to_po"]["po"] == "70111303"


def test_economic_weeks_bounds():
    assert economic_weeks(0, 10, POL) == POL.min_cover_weeks
    assert economic_weeks(1000, 0, POL) == POL.no_cost_weeks
    assert economic_weeks(0.01, 0.01, POL) == POL.max_cover_weeks


def test_size_all_rewrites_qty_and_keeps_minimum():
    info = Part("35-0126-00G", "B", "cable", unit_cost=36.0)
    buys = _weekly_buys(info.part, 20, 10)
    b = {"part": info.part, "qty": 10.0, "spend": 360.0, "unit_cost": 36.0, "pack_qty": 0}
    open_pos = pd.DataFrame(
        [
            {
                "po": "70111303",
                "part": info.part,
                "created": pd.Timestamp(TODAY - timedelta(days=1)),
                "qty_due": 14.0,
                "buyer": "RM",
            }
        ]
    )
    size_all(
        [b],
        buys,
        {info.part: _demands(info.part, 20, 10)},
        {info.part: info},
        open_pos,
        set(),
        PlanSettings(),
        TODAY,
    )
    assert b["min_qty"] == 10 and b["qty"] > 10 and b["spend"] == b["qty"] * 36
    assert b["sizing"]["add_to_po"]["po"] == "70111303"
    assert "weeks" in b["sizing"]["why"]


def test_past_due_first_need_does_not_eat_the_window():
    info = Part("94-3152-00G", "B", "", unit_cost=20.0)
    past = TODAY - timedelta(days=40)
    buys = _weekly_buys(info.part, 16, 25, start=past)
    rec = size_buy(info.part, info, buys, 75, _demands(info.part, 16, 25, start=past), TODAY, POL)
    assert rec["covers_until"] > TODAY + timedelta(days=42)


def _ss_buy(part, qty, place_by):
    return PlannedOrder(part, "buy", qty, place_by + timedelta(days=42), place_by, 30, "x", (),
                        shortfall=qty, reason="safety_stock")


def test_machine_shop_safety_stock_top_up_waits_for_the_next_booked_buy():
    # 62-1132-01G on 11-06: 1 to restore safety stock, 36 booked from April
    info = Part("62-1132-01G", "B", "TEST FIBER PLATE", unit_cost=113.29)
    later = _weekly_buys(info.part, 3, 12, start=TODAY + timedelta(days=150))
    buys = [_ss_buy(info.part, 1, TODAY)] + later
    rec = size_buy(info.part, info, buys, 1, _demands(info.part, 3, 12), TODAY, POL,
                   setup=True, ss_only=True)
    assert rec["policy"] == "hold" and rec["qty"] == 0
    assert rec["hold"]["place_by"] == later[0].place_by
    assert rec["hold"]["qty"] == 13 and rec["hold"]["ss_qty"] == 1
    assert "next buy" in why_words(rec, 113.29)
    # a critical part, or a vendor without setup, still tops up now
    for kw in ({"setup": True, "ss_only": True, "critical": True}, {"ss_only": True}):
        rec = size_buy(info.part, info, buys, 1, _demands(info.part, 3, 12), TODAY, POL, **kw)
        assert rec["policy"] != "hold" and rec["qty"] >= 1


def test_no_booked_buy_ahead_means_no_hold():
    info = Part("P", "B", "", unit_cost=100.0)
    rec = size_buy("P", info, [_ss_buy("P", 1, TODAY)], 1, [], TODAY, POL, setup=True, ss_only=True)
    assert rec["policy"] == "minimum" and rec["qty"] == 1
    assert "lot price" in why_words(rec, 100.0)


def test_setup_cost_stretches_a_machine_shop_buy():
    rate, cost = 5.0, 142.32
    plain = economic_weeks(rate, cost, POL)
    shop = economic_weeks(rate, cost, POL, POL.setup_order_cost)
    assert shop > plain * 2
    assert economic_weeks(1.1, cost, POL, POL.setup_order_cost) == POL.max_cover_weeks


def test_a_vendor_quote_is_trusted_where_part_vendor_rows_are_not():
    # one-off price ~6x the unit cost: Part_Vendor's band check rejects it
    info = Part("62-1147-02G", "B", "", unit_cost=108.67)
    buys = _weekly_buys(info.part, 20, 1)
    quote = [(1, 717.59), (2, 382.76), (5, 181.86), (10, 114.90), (15, 92.58)]
    pol = OrderPolicy(order_cost=1.0)  # two weeks of cover: 2 or 3 pieces
    args = (info.part, info, buys, 1, _demands(info.part, 20, 1), TODAY, pol)
    assert size_buy(*args, breaks=quote)["price_break"] is None
    rec = size_buy(*args, breaks=quote, quoted=True)
    assert rec["price_break"] and rec["qty"] == 5


def test_size_all_uses_a_current_quote_and_drops_held_qty():
    from pkmrp.core.quotes import current_quotes

    q = current_quotes(TODAY, {"quotes": [{"vendor": "DUYCK MACHINE INC", "quote": "Q1",
                                           "date": "2026-10-20", "use_days": 30,
                                           "parts": {"A": [[1, 700], [10, 110]]}}]})
    assert q["A"]["breaks"] == [[1.0, 700.0], [10.0, 110.0]]
    assert current_quotes(TODAY + timedelta(days=30), {"quotes": [
        {"vendor": "D", "date": "2026-10-20", "use_days": 30, "parts": {"A": [[1, 1]]}}]}) == {}
    parts = {"A": Part("A", "B", "", unit_cost=110.0)}
    planned = [_ss_buy("A", 1, TODAY)] + _weekly_buys("A", 4, 3, start=TODAY + timedelta(days=90))
    buys = [{"part": "A", "qty": 1.0, "spend": 110.0, "unit_cost": 110.0,
             "vendor": "DUYCK MACHINE INC", "ss_only": True, "critical": False}]
    empty = pd.DataFrame(columns=["part", "po", "created", "qty_due", "buyer"])
    size_all(buys, planned, {}, parts, empty, set(), PlanSettings(), TODAY, quotes=q)
    assert buys[0]["sizing"]["policy"] == "hold" and buys[0]["qty"] == 0
