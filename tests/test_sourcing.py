from datetime import date, timedelta

import pandas as pd

from pkmrp.core.netting import Demand, Part, Peg
from pkmrp.core.sourcing import SourcingPolicy, build, make_or_buy, price_breaks
from pkmrp.core.vendor_price import build as vp_build

TODAY = date(2026, 10, 30)


def D(days):
    return TODAY - timedelta(days=days)


def _rec(rows):
    return pd.DataFrame(
        [
            {
                "date": pd.Timestamp(d),
                "po": po,
                "line": "01",
                "delivery": "01",
                "part": p,
                "vendor_id": v,
                "qty": q,
                "unit_price": pr,
                "std_cost": std,
                "invoice": "",
            }
            for d, po, p, v, q, pr, std in rows
        ],
        columns=[
            "date",
            "po",
            "line",
            "delivery",
            "part",
            "vendor_id",
            "qty",
            "unit_price",
            "std_cost",
            "invoice",
        ],
    )


EMPTY_OPEN = pd.DataFrame(
    columns=[
        "po",
        "line",
        "delivery",
        "part",
        "vendor_id",
        "created",
        "cur_due",
        "qty_due",
        "unit_price",
        "std_cost",
    ]
)


def _frames():
    dmr = pd.DataFrame([{"vendor_id": "BAD", "part": "P1", "returns": 2, "qty_returned": 40.0}])
    brk = pd.DataFrame(
        columns=["part", "vendor_id", "break1", "cost1", "break2", "cost2", "break3", "cost3"]
    )
    mc = pd.DataFrame(columns=["part", "material", "labor", "hours"])
    wo = pd.DataFrame(columns=["part", "work_orders", "qty_built", "last_built"])
    bom = pd.DataFrame(columns=["parent", "component", "qty_per", "type_code", "effective"])
    return dmr, brk, mc, wo, bom


def test_switch_needs_delivery_and_quality_not_just_price():
    rec = _rec(
        [
            (D(30), "70110001", "P1", "NOW", 100, 20.0, 18.0),
            (D(200), "70105000", "P1", "CHEAP", 100, 15.0, 18.0),  # cheaper, fine
            (D(100), "70107000", "P1", "BAD", 100, 12.0, 18.0),  # cheapest but sends 40% back
            (D(150), "70106000", "P1", "LATE", 100, 13.0, 18.0),  # cheaper but late
        ]
    )
    vp = vp_build(rec, EMPTY_OPEN, {}, {}, {}, TODAY)
    delivery = [
        {"vendor_id": "NOW", "on_time_pct": 80.0},
        {"vendor_id": "CHEAP", "on_time_pct": 85.0},
        {"vendor_id": "BAD", "on_time_pct": 90.0},
        {"vendor_id": "LATE", "on_time_pct": 40.0},
    ]
    dmr, brk, mc, wo, bom = _frames()
    parts = {"P1": Part("P1", "B", "bracket", unit_cost=18.0)}
    demands = {"P1": [Demand("P1", TODAY + timedelta(days=60), 1000, (), "so")]}
    out = build(
        vp,
        delivery,
        dmr,
        brk,
        mc,
        wo,
        [],
        parts,
        bom,
        demands,
        {"NOW": "NOW", "CHEAP": "CHEAP", "BAD": "BAD", "LATE": "LATE"},
        TODAY,
    )
    sw = [s for s in out["ideas"] if s["kind"] == "switch"]
    assert len(sw) == 1 and sw[0]["to_vendor_id"] == "CHEAP"
    assert sw[0]["saving"] == (20 - 15) * 1000 and not sw[0]["check_scope"]


def test_huge_gap_is_flagged_and_left_out_of_the_headline():
    rec = _rec(
        [
            (D(30), "70110001", "P1", "NOW", 100, 20.43, 20.0),
            (D(60), "70105000", "P1", "RAW", 100, 3.66, 20.0),
        ]
    )
    vp = vp_build(rec, EMPTY_OPEN, {}, {}, {}, TODAY)
    dmr, brk, mc, wo, bom = _frames()
    out = build(
        vp,
        [],
        dmr.iloc[0:0],
        brk,
        mc,
        wo,
        [],
        {"P1": Part("P1", "B", "", unit_cost=20)},
        bom,
        {"P1": [Demand("P1", TODAY + timedelta(days=30), 500, (), "so")]},
        {},
        TODAY,
    )
    sw = out["ideas"][0]
    assert sw["check_scope"] and out["savings"] == 0


def test_price_break_only_when_quote_matches_what_was_paid():
    pol = SourcingPolicy()
    buys = [{"part": "M", "qty": 11, "vendor_id": "HK", "vendor": "HK"}]
    brs = {("M", "HK"): [(1, 197.9), (25, 176.41)]}
    out = price_breaks(buys, brs, {("HK", "M"): 197.9}, {"M": 20}, {}, pol)
    assert out and out[0]["evidence"]["break_qty"] == 25
    # quote kept per pack of 100: ignored
    assert (
        price_breaks(
            buys, {("M", "HK"): [(1, 19790), (25, 17641)]}, {("HK", "M"): 197.9}, {"M": 20}, {}, pol
        )
        == []
    )


def test_make_needs_a_real_gap_and_systems_are_never_outsourcing_candidates():
    pol = SourcingPolicy()
    parts = {
        "62-3850-00G": Part("62-3850-00G", "B", "carriage w/ bearing", unit_cost=535),
        "62-0378-01G": Part("62-0378-01G", "B", "carriage", unit_cost=171.58),
        "62-0122-00G": Part("62-0122-00G", "B", "retainer", unit_cost=28.08),
        "01-2880-03G": Part("01-2880-03G", "A", "2880 system"),
        "06-9999-00G": Part("06-9999-00G", "A", "big subassembly"),
    }
    bom = {"62-3850-00G": [("62-0378-01G", 1), ("62-0122-00G", 1)]}
    uc = {p: v.unit_cost for p, v in parts.items()}
    mc = {"01-2880-03G": (20000, 0, 62.0), "06-9999-00G": (500, 0, 10.0)}
    out = make_or_buy(
        parts,
        bom,
        uc,
        mc,
        {"62-3850-00G": (4, 57, TODAY)},
        {"62-3850-00G": (535.0, "ALASER", "70101020")},
        lambda p: 50,
        {},
        {},
        pol,
        sold={"01-2880-03G"},
    )
    kinds = {(s["kind"], s["part"]) for s in out}
    assert ("make", "62-3850-00G") in kinds
    assert ("buy", "06-9999-00G") in kinds and ("buy", "01-2880-03G") not in kinds
    mk = next(s for s in out if s["part"] == "62-3850-00G")
    assert mk["evidence"]["break_even_hours"] == round((535 - 199.66) / 171, 1)
    assert mk["evidence"]["built_before"] == 4


def test_negotiate_and_standards_from_price_data():
    rows = []
    for i in range(30):
        rows.append((D(500), f"7010{i:04d}", f"P{i}", "SHOP", 100, 100.0, 80.0))
        rows.append((D(60), f"7011{i:04d}", f"P{i}", "SHOP", 100, 110.0, 80.0))
    vp = vp_build(_rec(rows), EMPTY_OPEN, {"SHOP": "SHOP"}, {}, {}, TODAY)
    dmr, brk, mc, wo, bom = _frames()
    out = build(vp, [], dmr.iloc[0:0], brk, mc, wo, [], {}, bom, {}, {"SHOP": "SHOP"}, TODAY)
    assert any(s["kind"] == "negotiate" and s["vendor_id"] == "SHOP" for s in out["ideas"])
    assert len(out["standards"]) == 30 and out["standards"][0]["evidence"]["gap_pct"] == 37.5


def test_peg_root_marks_sold_parts():
    d = Demand("06-1", TODAY, 1, (Peg("so", "SO 1/01", "01-SYS"),), "so")
    assert {p.root_part for p in d.pegs} == {"01-SYS"}
