from datetime import date, timedelta

import pandas as pd

from pkmrp.core.netting import Demand, Part, PlannedOrder
from pkmrp.core.order_qty import OrderPolicy, economic_weeks, size_all, size_buy
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


def test_committed_part_follows_its_blanket():
    info = Part("Z", "B", "", unit_cost=5.0)
    buys = _weekly_buys("Z", 10, 10)
    rec = size_buy("Z", info, buys, 10, _demands("Z", 10, 10), TODAY, POL, committed=True)
    assert rec["qty"] == 10 and rec["policy"] == "committed" and rec["later_qty"] == 90


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
