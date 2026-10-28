"""core/segment.py and core/params.py."""

from datetime import date

import pandas as pd

from pkmrp.core.netting import Part
from pkmrp.core.params import purlt_proposals
from pkmrp.core.segment import classify, gated_orders, sources
from pkmrp.core.settings import PlanSettings

TODAY = date(2026, 10, 28)
S = PlanSettings()


def lt(median, p80, lines, purlt, source=None):
    return {
        "median": median,
        "p80": p80,
        "lines": lines,
        "early_lines": 0,
        "vendor": "V",
        "purlt": purlt,
        "ratio": None,
        "source": source or (f"realized ({lines} lines)" if lines >= 3 else "PURLT_01"),
    }


def test_gated_orders_walk_the_bom_and_skip_far_and_placeholder_dates():
    so = pd.DataFrame(
        {
            "so": ["1", "2", "3"],
            "part": ["SYS", "SYS", "SYS"],
            "cus_due": [
                pd.Timestamp("2027-01-15"),
                pd.Timestamp("2028-06-01"),
                pd.Timestamp("2033-12-29"),
            ],
            "cur_due": [pd.NaT] * 3,
        }
    )
    kids = {"SYS": [("SUB", 1.0)], "SUB": [("LENS", 2.0)]}
    g = gated_orders(so, kids, S, TODAY)
    assert g["LENS"] == {"1"} and g["SYS"] == {"1"}


def test_committed_needs_proven_history_unproven_is_its_own_group():
    parts = {p: Part(p, "B", purchase_lt=100) for p in ("LONG", "GUESS", "SHORT")}
    stats = {"LONG": lt(80, 90, 6, 100), "GUESS": lt(100, 100, 0, 100), "SHORT": lt(20, 30, 5, 100)}
    gated = {"LONG": {"1"}, "GUESS": {"1"}, "SHORT": {"1"}}
    out = {r["part"]: r["segment"] for r in classify(parts, stats, {}, {}, gated, {"1": 1e6}, S)}
    assert out == {"LONG": "committed", "GUESS": "unproven_long", "SHORT": "order_driven"}


def test_single_source_rule_is_off_by_default():
    parts = {"P": Part("P", "B", purchase_lt=60)}
    stats = {"P": lt(50, 70, 5, 60)}  # 98 calendar days at P80? no: 70 bdays -> 98 cal > 90
    stats = {"P": lt(40, 55, 5, 60)}  # 77 cal: single-source band only
    gated = {"P": {"1"}}
    one = classify(parts, stats, {"P": {"V"}}, {"P": {"V"}}, gated, {"1": 5e7}, S)
    assert one[0]["segment"] == "order_driven" and one[0]["single_source"]
    on = PlanSettings(single_source_gate=500_000.0)
    assert (
        classify(parts, stats, {"P": {"V"}}, {"P": {"V"}}, gated, {"1": 5e7}, on)[0]["segment"]
        == "committed"
    )


def test_sources_counts_approved_and_used_separately():
    pv = pd.DataFrame({"part": ["P", "P"], "vendor_id": ["A", "B"]})
    hist = pd.DataFrame({"part": ["P", "P"], "vendor_id": ["A", ""]})
    approved, used = sources(pv, hist)
    assert approved["P"] == {"A", "B"} and used["P"] == {"A"}


def test_purlt_proposals_round_up_p80_and_skip_thin_or_close_history():
    parts = {p: Part(p, "B", description=p) for p in ("FAST", "SLOW", "CLOSE", "THIN")}
    stats = {
        "FAST": lt(20, 23, 6, 85),
        "SLOW": lt(144, 261, 3, 85),
        "CLOSE": lt(80, 90, 6, 85),
        "THIN": lt(10, 10, 2, 85),
    }
    out = {r["part"]: r for r in purlt_proposals(parts, stats)}
    assert set(out) == {"FAST", "SLOW"}
    assert out["FAST"]["proposed_bdays"] == 25 and out["FAST"]["direction"] == "shorter"
    # 3 receipts: the median, not one slow PO's P80
    assert out["SLOW"]["proposed_bdays"] == 145 and out["SLOW"]["basis"] == "median"
    assert out["FAST"]["basis"] == "P80" and out["SLOW"]["direction"] == "longer"
    assert list(out) == ["FAST", "SLOW"]  # both change by 60: ties sort by part
