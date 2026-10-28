"""The deterministic core: calendar, BOM, netting, demand, lead time."""

from datetime import date

import pandas as pd

from pkmrp.core.bom import children_map, low_level_codes
from pkmrp.core.calendar import as_date, minus_workdays, workdays_between
from pkmrp.core.demand import backlog_demand
from pkmrp.core.leadtime import realized
from pkmrp.core.netting import Demand, Part, Peg, Receipt, plan
from pkmrp.core.settings import PlanSettings

TODAY = date(2026, 10, 28)  # a Wednesday
S = PlanSettings()


def peg(ref="SO 1/01", root="SYS"):
    return (Peg("so", ref, root, (root,), 1000.0),)


def kinds(result):
    return sorted(e.kind for e in result.exceptions)


# ── calendar ──────────────────────────────────────────────────────────


def test_workdays_skip_weekends_and_holidays():
    assert minus_workdays(date(2026, 11, 2), 1) == date(2026, 10, 30)  # Mon -> Fri
    assert minus_workdays(date(2026, 11, 2), 1, {date(2026, 10, 30)}) == date(2026, 10, 29)
    assert workdays_between(date(2026, 10, 30), date(2026, 11, 2)) == 1
    assert workdays_between(date(2026, 11, 2), date(2026, 10, 30)) == -1


def test_as_date_handles_nat_and_timestamps():
    assert as_date(pd.NaT) is None and as_date(None) is None and as_date(float("nan")) is None
    assert as_date(pd.Timestamp("2026-10-28 13:00")) == TODAY


# ── BOM ───────────────────────────────────────────────────────────────


def test_low_level_codes_take_the_deepest_use():
    kids = children_map([("SYS", "SUB", 1), ("SUB", "SCREW", 4), ("SYS", "SCREW", 2)])
    level, dropped = low_level_codes(kids)
    assert (level["SYS"], level["SUB"], level["SCREW"]) == (0, 1, 2) and not dropped


def test_cycles_are_dropped_and_reported():
    kids = children_map([("A", "B", 1), ("B", "C", 1), ("C", "A", 1)])
    level, dropped = low_level_codes(kids)
    assert len(dropped) == 1
    assert len(set(level.values())) == 3  # a strict order still exists


def test_children_map_sums_duplicates_and_drops_zero_qty():
    assert children_map([("P", "C", 1), ("P", "C", 2), ("P", "Z", 0)]) == {"P": [("C", 3.0)]}


# ── netting ───────────────────────────────────────────────────────────


def buy(part="LENS", lt=20, **kw):
    return Part(part, "B", purchase_lt=lt, **kw)


def test_on_hand_covers_demand_no_order():
    r = plan(
        {"LENS": buy()},
        {},
        [Demand("LENS", date(2026, 12, 1), 5, peg(), "so")],
        {"LENS": 5},
        [],
        S,
        TODAY,
    )
    assert r.planned == [] and r.exceptions == []


def test_shortage_makes_a_buy_with_place_by_and_late_flag():
    d = Demand("LENS", date(2026, 11, 13), 10, peg(), "so")
    r = plan({"LENS": buy(lt=20)}, {}, [d], {"LENS": 4}, [], S, TODAY)
    (o,) = r.planned
    assert (o.kind, o.qty, o.shortfall, o.need_by) == ("buy", 6, 6, date(2026, 11, 13))
    assert o.place_by == minus_workdays(date(2026, 11, 13), 20) and o.late
    assert "late_to_place" in kinds(r) and o.pegs == d.pegs


def test_receipt_due_after_need_is_an_expedite_not_a_new_buy():
    r = plan(
        {"LENS": buy()},
        {},
        [Demand("LENS", date(2026, 11, 20), 10, peg(), "so")],
        {},
        [Receipt("LENS", date(2026, 12, 15), 10, "po", "PO 7/01/00")],
        S,
        TODAY,
    )
    assert r.planned == []
    (e,) = r.exceptions
    assert (e.kind, e.ref, e.days) == ("expedite_open_po", "PO 7/01/00", 25)


def test_unused_receipt_is_cancel_candidate_and_early_one_push_out():
    recs = [
        Receipt("LENS", date(2026, 11, 2), 5, "po", "PO A"),
        Receipt("LENS", date(2026, 11, 3), 5, "po", "PO B"),
    ]
    r = plan(
        {"LENS": buy()}, {}, [Demand("LENS", date(2027, 3, 1), 5, peg(), "so")], {}, recs, S, TODAY
    )
    assert kinds(r) == ["cancel_candidate", "push_out_open_po"]


def test_min_and_mult_round_up_and_surplus_covers_later_demand():
    part = buy(min_qty=10, mult_qty=5)
    ds = [
        Demand("LENS", date(2026, 12, 1), 3, peg("SO 1/01"), "so"),
        Demand("LENS", date(2026, 12, 8), 6, peg("SO 2/01"), "so"),
    ]
    r = plan({"LENS": part}, {}, ds, {}, [], S, TODAY)
    (o,) = r.planned
    assert o.qty == 10 and o.shortfall == 3  # 10 covers both lines


def test_make_part_explodes_offset_by_mfg_lead_time_with_pegs():
    parts = {"SYS": Part("SYS", "A", mfg_lt=10), "LENS": buy(lt=5)}
    kids = {"SYS": [("LENS", 2.0)]}
    r = plan(
        parts, kids, [Demand("SYS", date(2026, 12, 15), 3, peg("SO 9/01"), "so")], {}, [], S, TODAY
    )
    make = next(o for o in r.planned if o.kind == "make")
    lens = next(o for o in r.planned if o.part == "LENS")
    assert make.place_by == minus_workdays(date(2026, 12, 15), 10)
    assert lens.qty == 6 and lens.need_by == make.place_by
    assert lens.pegs[0].ref == "SO 9/01" and lens.pegs[0].path == ("SYS", "LENS")


def test_subassembly_on_hand_stops_explosion():
    parts = {"SYS": Part("SYS", "A"), "SUB": Part("SUB", "A"), "LENS": buy()}
    kids = {"SYS": [("SUB", 1.0)], "SUB": [("LENS", 1.0)]}
    r = plan(
        parts, kids, [Demand("SYS", date(2026, 12, 1), 2, peg(), "so")], {"SUB": 2}, [], S, TODAY
    )
    assert {o.part for o in r.planned} == {"SYS"}


def test_unplanned_types_docs_and_unknown_parts_are_reported_not_ordered():
    parts = {"SYS": Part("SYS", "A"), "TUBE": Part("TUBE", "Y"), "90-1": Part("90-1", "A")}
    kids = {"SYS": [("TUBE", 1.0), ("90-1", 1.0), ("GHOST", 1.0)]}
    r = plan(parts, kids, [Demand("SYS", date(2026, 12, 1), 1, peg(), "so")], {}, [], S, TODAY)
    assert {o.part for o in r.planned} == {"SYS"}
    assert kinds(r) == ["short_unplanned_type", "unknown_part"]


def test_make_without_bom_is_flagged():
    r = plan(
        {"CF": Part("CF", "A")},
        {},
        [Demand("CF", date(2026, 12, 1), 1, peg(), "so")],
        {},
        [],
        S,
        TODAY,
    )
    assert "make_without_bom" in kinds(r)


def test_plan_is_deterministic():
    parts = {"SYS": Part("SYS", "A", mfg_lt=3), "L": buy(), "M": buy()}
    kids = {"SYS": [("L", 1.0), ("M", 2.0)]}
    ds = [Demand("SYS", date(2026, 12, 1), 2, peg(), "so")]
    a = plan(parts, kids, ds, {}, [], S, TODAY)
    b = plan(parts, kids, ds, {}, [], S, TODAY)
    assert [(o.part, o.qty, o.place_by) for o in a.planned] == [
        (o.part, o.qty, o.place_by) for o in b.planned
    ]


# ── demand ────────────────────────────────────────────────────────────


def test_backlog_worklists_unscheduled_no_date_and_unplannable():
    so = pd.DataFrame(
        {
            "so": ["1", "2", "3", "4"],
            "line": ["01"] * 4,
            "part": ["L", "L", "L", "CF"],
            "qty_due": [1.0, 1.0, 1.0, 1.0],
            "cus_due": [
                pd.Timestamp("2026-12-01"),
                pd.Timestamp("2033-12-29"),
                pd.NaT,
                pd.Timestamp("2026-12-01"),
            ],
            "cur_due": [pd.NaT] * 4,
            "unit_price": [100.0, 0.0, 0.0, 50.0],
            "customer": ["X"] * 4,
        }
    )
    demands, work = backlog_demand(so, S, has_bom=set(), on_hand={}, part_types={"CF": "A"})
    assert [d.part for d in demands] == ["L", "CF"]
    assert len(work["unscheduled"]) == 1 and len(work["no_date"]) == 1
    assert [w["part"] for w in work["unplannable"]] == ["CF"]
    assert demands[0].pegs[0].value == 100.0


# ── lead time ─────────────────────────────────────────────────────────


def _hist(rows):
    cols = [
        "part",
        "vendor_id",
        "created",
        "org_due",
        "last_receipt",
        "qty_current",
        "qty_received",
    ]
    return pd.DataFrame(rows, columns=cols)


def test_realized_median_skips_partial_and_early_lines():
    rows = [
        (
            "L",
            "V",
            pd.Timestamp("2026-01-05"),
            pd.Timestamp("2026-02-02"),
            pd.Timestamp("2026-02-02"),
            10,
            10,
        )
    ] * 3
    rows.append(
        (
            "L",
            "V",
            pd.Timestamp("2026-01-05"),
            pd.Timestamp("2026-02-02"),
            pd.Timestamp("2026-06-01"),
            10,
            2,
        )
    )  # partial: ignored
    rows.append(
        (
            "L",
            "V",
            pd.Timestamp("2026-01-05"),
            pd.Timestamp("2026-12-01"),
            pd.Timestamp("2026-12-01"),
            10,
            10,
        )
    )  # ordered early: excluded
    s = realized(_hist(rows), {"L": 20})["L"]
    assert s["median"] == 20 and s["lines"] == 3 and s["early_lines"] == 1
    assert s["source"].startswith("realized")


def test_lead_time_falls_back_to_purlt():
    s = realized(_hist([]), {"L": 30})["L"]
    assert (s["median"], s["source"]) == (30, "PURLT_01")


def test_one_expedite_per_receipt_with_earliest_need_and_total_qty():
    ds = [
        Demand("LENS", date(2026, 11, 2), 2, peg("SO 1/01"), "so"),
        Demand("LENS", date(2026, 11, 9), 3, peg("SO 2/01"), "so"),
    ]
    r = plan(
        {"LENS": buy()}, {}, ds, {}, [Receipt("LENS", date(2026, 12, 1), 5, "po", "PO X")], S, TODAY
    )
    (e,) = r.exceptions
    assert (e.kind, e.qty, e.days) == ("expedite_open_po", 5, 29)
    assert {p.ref for p in e.pegs} == {"SO 1/01", "SO 2/01"}


def test_vendor_fallback_needs_same_class_and_enough_lines():
    rows = [
        (
            "R1",
            "DIGI",
            pd.Timestamp("2026-01-05"),
            pd.Timestamp("2026-01-12"),
            pd.Timestamp("2026-01-12"),
            10,
            10,
        )
    ] * 12
    lt = realized(
        _hist(
            rows
            + [
                (
                    "FPGA",
                    "DIGI",
                    pd.Timestamp("2026-01-05"),
                    pd.Timestamp("2026-01-12"),
                    pd.Timestamp("2026-01-12"),
                    1,
                    1,
                ),
                # One line of its own: its vendor is known, its history too thin.
                (
                    "R2",
                    "DIGI",
                    pd.Timestamp("2026-01-05"),
                    pd.Timestamp("2026-01-12"),
                    pd.Timestamp("2026-01-12"),
                    1,
                    1,
                ),
            ]
        ),
        {"R1": 5, "FPGA": 370, "R2": 5},
        {"R1": "RES", "FPGA": "IC", "R2": "RES"},
        vendor_fallback=True,
    )
    assert lt["FPGA"]["source"] == "PURLT_01" and lt["FPGA"]["median"] == 370
    assert lt["R2"]["source"].startswith("vendor DIGI")


def test_vendor_fallback_is_off_by_default():
    row = (
        "R1",
        "DIGI",
        pd.Timestamp("2026-01-05"),
        pd.Timestamp("2026-01-12"),
        pd.Timestamp("2026-01-12"),
        10,
        10,
    )
    lt = realized(_hist([row] * 12), {"R1": 5, "R2": 5}, {"R1": "RES", "R2": "RES"})
    assert lt["R2"]["source"] == "PURLT_01"


def test_unused_receipt_on_a_long_lead_part_is_beyond_backlog_not_cancel():
    r = plan(
        {"FPGA": buy("FPGA", lt=370)},
        {},
        [],
        {},
        [Receipt("FPGA", date(2027, 6, 18), 203, "po", "PO 70111155")],
        S,
        TODAY,
    )
    assert kinds(r) == ["beyond_backlog"]
