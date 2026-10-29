"""core/pipeline.py: Book/Bill 2.0 bookings as weighted demand."""

import pandas as pd

from pkmrp.core.pipeline import pipeline_demand
from pkmrp.core.settings import PlanSettings

S = PlanSettings()


def lines(*rows):
    cols = [
        "booking_id",
        "booking",
        "customer",
        "status",
        "p_win",
        "p_go",
        "bill_year",
        "bill_month",
        "item_id",
        "sku",
        "description",
        "qty",
        "option_of",
    ]
    return pd.DataFrame(rows, columns=cols)


def test_weighted_by_win_dated_by_billing_month_and_mapped_or_worklisted():
    df = lines(
        (1, "BK-1", "Acme", "open", 50, 20, 2027, 3, 11, "01-2300AG-07G", "2300AG", 2, None),
        (1, "BK-1", "Acme", "open", 50, 20, 2027, 3, 12, "2300-OPT-X", "fancy option", 4, 11),
        (2, "BK-2", "Zed", "open", 80, 90, None, None, 21, "01-2300AG-07G", "2300AG", 1, None),
        (3, "BK-3", "Zed", "open", 0, 90, 2027, 4, 31, "01-2300AG-07G", "2300AG", 1, None),
    )
    frame, work = pipeline_demand(df, {"01-2300AG-07G"}, {}, S)
    assert list(frame["part"]) == ["01-2300AG-07G"] and list(frame["qty_due"]) == [1.0]
    assert frame["cus_due"].iloc[0] == pd.Timestamp("2027-03-01")
    assert work["undated_bookings"] == 1 and work["bookings"] == 1
    assert work["unmapped"][0]["sku"] == "2300-OPT-X" and work["unmapped"][0]["weighted_qty"] == 2.0


def test_sku_map_and_go_probability():
    df = lines((1, "BK-1", "Acme", "open", 50, 20, 2027, 3, 12, "2300-OPT-X", "opt", 4, 11))
    frame, work = pipeline_demand(df, set(), {"2300-OPT-X": "00-2021-02G"}, S)
    assert list(frame["part"]) == ["00-2021-02G"] and not work["unmapped"]
    frame, _ = pipeline_demand(
        df, set(), {"2300-OPT-X": "00-2021-02G"}, PlanSettings(pipeline_use_go=True)
    )
    assert frame["qty_due"].iloc[0] == 0.4  # 4 x 0.5 x 0.2


def test_qty_per_skip_and_undated_list():
    df = lines(
        (1, "BK-1", "Acme", "open", 50, 0, 2027, 3, 11, "1050C System", "", 2, None),
        (1, "BK-1", "Acme", "open", 50, 0, 2027, 3, 12, "1050-LIC", "license", 1, 11),
        (2, "BK-2", "Zed", "open", 80, 0, None, None, 21, "1050C System", "", 1, None),
    )
    sku_map = {"1050C System": {"part": "01-1050C-03G", "qty_per": 2}, "1050-LIC": {"skip": True}}
    frame, work = pipeline_demand(df, set(), sku_map, S)
    assert list(frame["qty_due"]) == [2.0]  # 2 x 2 per x 0.5
    assert work["skipped"] == {"1050-LIC": 0.5} and not work["unmapped"]
    assert work["undated"][0]["booking"] == "BK-2" and work["undated"][0]["skus"] == [
        "1050C System"
    ]
