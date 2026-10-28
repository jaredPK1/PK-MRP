"""core/committed.py: 12-month requirement, buffer, blanket releases."""

from datetime import date

import pandas as pd

from pkmrp.core.committed import monthly_requirement, plan_part
from pkmrp.core.netting import Part
from pkmrp.core.settings import PlanSettings

TODAY = date(2026, 10, 28)
S = PlanSettings()


def so(*rows):
    return pd.DataFrame(
        [
            {"so": s, "part": p, "qty_due": q, "cus_due": pd.Timestamp(d), "cur_due": pd.NaT}
            for s, p, q, d in rows
        ]
    )


def test_requirement_walks_the_bom_and_pulls_earlier_by_build_time():
    parts = {"SYS": Part("SYS", "A", mfg_lt=25), "LENS": Part("LENS", "B")}
    kids = {"SYS": [("LENS", 2.0)]}
    m = monthly_requirement(
        ["LENS"],
        so(("1", "SYS", 3, "2027-03-20"), ("2", "SYS", 1, "2033-12-29")),
        kids,
        parts,
        S,
        TODAY,
    )
    assert m["LENS"] == {date(2027, 2, 1): 6.0}  # 25 working days before 3/20, placeholder skipped


def test_past_due_counts_in_the_current_month():
    parts = {"LENS": Part("LENS", "B")}
    m = monthly_requirement(["LENS"], so(("1", "LENS", 4, "2026-09-01")), {}, parts, S, TODAY)
    assert m["LENS"] == {date(2026, 10, 1): 4.0}


def test_plan_releases_ahead_of_need_and_holds_a_buffer():
    info = Part("LENS", "B", description="LENS", yield_pct=80)
    months = {date(2027, 1, 1): 10.0, date(2027, 4, 1): 10.0}
    cp = plan_part(
        "LENS",
        info,
        months,
        60,
        on_hand=5,
        open_pos=[(date(2026, 12, 1), 5, "PO 1")],
        settings=S,
        today=TODAY,
    )
    assert cp["yield_gross_up"] == 1.25 and cp["requirement_12m"] == 25.0
    assert cp["buffer"] > 0 and cp["blanket_qty"] >= 25 - 10
    jan = next(r for r in cp["releases"] if r["month"] == date(2027, 1, 1))
    assert jan["order_by"] < date(2027, 1, 1)
    assert [m["horizon"] for m in cp["schedule"][:7]] == ["frozen"] * 3 + ["firm"] * 3 + [
        "indicative"
    ]


def test_nothing_needed_means_no_buffer_and_no_blanket():
    cp = plan_part("X", Part("X", "B"), {}, 100, 0, [], S, TODAY)
    assert (cp["buffer"], cp["blanket_qty"], cp["releases"]) == (0, 0, [])
