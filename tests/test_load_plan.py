"""Parked orders planned into Load Plan months with room."""

from datetime import date

import pandas as pd

from pkmrp.core.load_plan import model_of, slot
from pkmrp.core.settings import PlanSettings

TODAY = date(2026, 11, 3)
S = PlanSettings()
PARK = "2034-12-29"


def line(so, ln, part, qty, price, cur_due, cus_due="2026-11-15", ordered="2026-10-01", ctype=""):
    return {
        "so": so, "line": ln, "delivery": "01", "part": part, "qty_due": qty,
        "unit_price": price, "cur_due": pd.Timestamp(cur_due), "cus_due": pd.Timestamp(cus_due),
        "customer": "C" + so, "customer_type": ctype, "order_date": pd.Timestamp(ordered),
        "currency": "USD",
    }


def run(rows, settings=S):
    df, summary = slot(pd.DataFrame(rows), settings, TODAY)
    return df, summary


def months(df, so):
    return sorted(df.loc[df["so"] == so, "load_month"].dropna().unique())


def test_model_prefixes_longest_first():
    assert model_of("01-2300-00G") == "2300"
    assert model_of("01-2302-01G") == "2302"
    assert model_of("01-2650-00G") == "2600"
    assert model_of("FLS-0001") == "FLS"
    assert model_of("99-1234-00G") is None


def test_dated_lines_untouched():
    df, s = run([line("1", "01", "01-8100-00G", 1, 100.0, "2027-02-10", "2027-01-20")])
    assert df.loc[0, "cus_due"] == pd.Timestamp("2027-01-20")
    assert s["placed"] == []


def test_parked_order_goes_to_first_month_with_room():
    rows = [line("A", "01", "01-2550-00G", 1, 0.0, "2026-11-20")]  # Nov full (cap 1)
    rows += [line("P", "01", "01-2550-00G", 1, 900_000.0, PARK, "2026-10-01")]
    df, s = run(rows)
    assert months(df, "P") == ["2026-12"]
    assert df.loc[df["so"] == "P", "cus_due"].iloc[0] == pd.Timestamp("2026-12-01")
    assert df.loc[df["so"] == "P", "cur_due"].iloc[0] == pd.Timestamp(PARK)  # MAX date kept


def test_never_before_customer_month():
    df, _ = run([line("P", "01", "99-0001-00G", 1, 10.0, PARK, "2027-04-15")])
    assert months(df, "P") == ["2027-04"]


def test_past_due_dated_line_takes_current_month_room():
    rows = [line("OLD", "01", "01-2550-00G", 1, 0.0, "2026-06-01")]
    rows += [line("P", "01", "01-2550-00G", 1, 0.0, PARK)]
    df, _ = run(rows)
    assert months(df, "P") == ["2026-12"]


def test_oldest_order_first():
    rows = [
        line("NEW", "01", "01-2550-00G", 1, 0.0, PARK, ordered="2026-10-20"),
        line("OLD", "01", "01-2550-00G", 1, 0.0, PARK, ordered="2026-01-07"),
    ]
    df, _ = run(rows)
    assert months(df, "OLD") == ["2026-11"]
    assert months(df, "NEW") == ["2026-12"]


def test_revenue_cap_moves_an_order():
    rows = [line("D", "01", "99-0001-00G", 1, 4_500_000.0, "2026-11-20")]
    rows += [line("P", "01", "99-0002-00G", 1, 600_000.0, PARK)]
    df, _ = run(rows)
    assert months(df, "P") == ["2026-12"]


def test_order_stays_together_when_it_fits():
    rows = [
        line("P", "01", "87-2300-00G", 1, 900_000.0, PARK),  # price header
        line("P", "02", "01-2300-00G", 1, 0.0, PARK),  # build line
    ]
    df, s = run(rows)
    assert months(df, "P") == ["2026-11"]
    assert s["placed"][0]["split"] is False


def test_big_order_spreads_line_by_line():
    rows = [line("P", "01", "01-0325-00G", 100, 1_000.0, PARK)]  # 100 cleavers, cap 40
    df, s = run(rows)
    got = df[df["so"] == "P"].sort_values("load_month")
    assert list(got["load_month"]) == ["2026-11", "2026-12", "2027-01"]
    assert list(got["qty_due"]) == [40.0, 40.0, 20.0]
    assert s["placed"][0]["split"] is True


def test_one_unit_bigger_than_a_month_goes_to_an_empty_month():
    rows = [line("D", "01", "99-0001-00G", 1, 100.0, "2026-11-20")]
    rows += [line("P", "01", "CF-0016-00G", 1, 6_000_000.0, PARK)]
    df, _ = run(rows)
    assert months(df, "P") == ["2026-12"]


def test_intercompany_takes_no_room_and_is_left_alone():
    rows = [line("IC", "01", "01-2550-00G", 1, 0.0, PARK, ctype="X")]
    rows += [line("P", "01", "01-2550-00G", 1, 0.0, PARK)]
    df, _ = run(rows)
    assert months(df, "IC") == []
    assert months(df, "P") == ["2026-11"]


def test_no_room_in_horizon_stays_parked():
    s = PlanSettings(load_horizon_months=1)
    rows = [line("A", "01", "01-2550-00G", 1, 0.0, "2026-11-20")]
    rows += [line("P", "01", "01-2550-00G", 1, 0.0, PARK)]
    df, summary = run(rows, s)
    assert df.loc[df["so"] == "P", "cus_due"].iloc[0] == pd.Timestamp(PARK)
    assert summary["unplaced"]
