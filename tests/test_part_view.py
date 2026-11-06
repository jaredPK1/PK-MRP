from datetime import date

from pkmrp.core.part_view import compare

TODAY = date(2026, 11, 6)


def _entry():
    return {
        "info": {"description": "pca", "type": "B", "max_ss": 20.0, "pk_ss": None},
        "pk": [
            [None, 10.0, "on_hand", "nettable stock"],
            ["2026-11-20", 30.0, "po", "PO 70111000"],
            ["2026-12-01", -25.0, "so", "SO 20048000/01"],
            ["2026-12-15", -15.0, "planned_make", "02-PARENT"],
            ["2027-09-01", -50.0, "so", "SO 20049000/01"],  # beyond 6 months
            ["2026-12-15", 15.0, "planned_buy", "place by 2026-11-10"],
        ],
        "pk_buys": [["2026-11-10", "2026-12-15", 15.0, "buy", "booked", False, ["SO 20048000/01"]]],
        "max_pl": [["2026-12-10", 60.0, "49370001", ""], ["2027-08-01", 40.0, "49370002", ""]],
        "max_dem": [
            ["2026-12-01", 25.0, "CU", "20048000", "", ""],
            ["2026-12-10", 70.0, "PL", "49360000", "03-PARENT", "ATP"],
            ["2027-01-05", 5.0, "MS", "MS1", "03-PARENT", ""],
        ],
        "max_act": [],
    }


def test_buckets_and_gap_over_six_months():
    v = compare(_entry(), TODAY, "6")
    b = {x["key"]: x for x in v["buckets"]}
    assert b["orders"]["pk"] == 25 and b["orders"]["max"] == 25
    assert b["parents"]["pk"] == 15 and b["parents"]["max"] == 70
    assert b["forecast"]["max"] == 5 and b["safety"]["max"] == 20
    assert v["pk_demand"] == 40 and v["max_demand"] == 120 and v["gap"] == 80
    assert v["biggest_gap"][0] == "parents"
    assert v["pk_buy_qty"] == 15 and v["max_buy_qty"] == 60


def test_supply_and_running_balance_exclude_planned_buys():
    v = compare(_entry(), TODAY, "6")
    assert v["on_hand"] == 10 and v["on_po"] == 30
    assert [t["balance"] for t in v["timeline"]] == [40, 15, 0]
    assert v["short_on"] is None


def test_everything_horizon_counts_far_demand():
    v = compare(_entry(), TODAY, "all")
    assert v["pk_demand"] == 90 and v["max_buy_qty"] == 100
    assert v["short_on"] == date(2027, 9, 1)
