"""core/skumap.py: proposing the MAX part a Book/Bill 2.0 SKU means."""

from datetime import date

import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from pkmrp.core.pipeline import resolve
from pkmrp.core.skumap import is_catch_all, key_of, propose
from pkmrp.db import store

TODAY = date(2026, 10, 29)
CATALOGUE = {
    "01-0351-00G": ("A", "FK11-SAE-U CLEAVER"),
    "01-1050C-03G": ("A", "1050 SERIES AUTOMATED FIBER ALIGNER"),
    "00-2720-00E": ("A", "1050C ACCESSORIES KIT"),
    "00-2840-00G": ("A", "OPTION, 2302-TCL THIN COATING"),
    "00-2840-00": ("A", "OPTION, 2302-TCL THIN COATING"),
    "00-2304-00": ("A", "OPTN, LOOSE FIBER RIBBON"),
    "DETAILS": ("X", "not a part"),
}
LAST = {
    "01-0351-00G": date(2026, 9, 1),
    "01-1050C-03G": date(2026, 6, 1),
    "00-2720-00E": date(2026, 6, 1),
    "00-2840-00G": date(2026, 3, 1),
    "00-2840-00": date(2019, 3, 1),
}


def frames(pairs):
    """pairs: (so, sku, sku_qty, [(part, qty), ...])"""
    booked = pd.DataFrame([(so, sku, q) for so, sku, q, _ in pairs], columns=["so", "sku", "qty"])
    lines = pd.DataFrame(
        [(so, p, q) for so, _s, _q, ps in pairs for p, q in ps], columns=["so", "part", "qty"]
    )
    return booked, lines


def test_keys_and_catch_alls():
    assert key_of("2311 System") == "2311" and key_of("2302-tcl") == "2302-TCL"
    assert is_catch_all("2304 Option") and not is_catch_all("1050C System")


def test_orders_and_name_agree_is_strong_and_qty_per_is_learned():
    booked, lines = frames(
        [(f"S{i}", "FK11-SAE-U", 1, [("01-0351-00G", 2), ("DETAILS", 1)]) for i in range(3)]
    )
    out = propose(["FK11-SAE-U"], booked, lines, CATALOGUE, LAST, TODAY)["FK11-SAE-U"]
    top = out["candidates"][0]
    assert out["confidence"] == "strong" and top["part"] == "01-0351-00G"
    assert top["qty_per"] == 2.0 and top["together"] == 3
    assert all(c["part"] != "DETAILS" for c in out["candidates"])  # not make/buy


def test_part_number_segment_beats_the_accessory_kit_that_ships_with_it():
    booked, lines = frames(
        [(f"S{i}", "1050C System", 1, [("01-1050C-03G", 1), ("00-2720-00E", 1)]) for i in range(2)]
    )
    out = propose(["1050C System"], booked, lines, CATALOGUE, LAST, TODAY)["1050C System"]
    assert out["candidates"][0]["part"] == "01-1050C-03G"
    assert "part number" in out["candidates"][0]["evidence"][0]


def test_name_alone_prefers_the_revision_sold_lately():
    booked, lines = frames([])
    out = propose(["2302-TCL"], booked, lines, CATALOGUE, LAST, TODAY)["2302-TCL"]
    assert [c["part"] for c in out["candidates"]][:2] == ["00-2840-00G", "00-2840-00"]
    assert out["orders"] == 0 and out["confidence"] in ("likely", "weak")


def test_catch_all_option_names_nothing_and_unknowns_have_no_candidates():
    booked, lines = frames([])
    out = propose(["2304 Option", "FLS1-10"], booked, lines, CATALOGUE, LAST, TODAY)
    assert out["2304 Option"]["catch_all"] and not out["2304 Option"]["candidates"]
    assert out["FLS1-10"]["confidence"] == "none"


def test_map_entries_resolve():
    assert resolve("01-0351-00G") == ("01-0351-00G", 1.0)
    assert resolve({"part": "01-0351-00G", "qty_per": 2}) == ("01-0351-00G", 2.0)
    assert resolve({"skip": True}) == "skip"
    assert resolve(None) is None and resolve("") is None


def test_settings_round_trip():
    e = create_engine("sqlite://", poolclass=StaticPool)
    store.metadata.create_all(e)
    assert store.get_setting(e, "pipeline_sku_map", {}) == {}
    store.put_setting(e, "pipeline_sku_map", {"FK12": {"part": "01-0324-00G"}}, "jared")
    store.put_setting(e, "pipeline_sku_map", {"FK12": {"skip": True}}, "jared")
    assert store.get_setting(e, "pipeline_sku_map") == {"FK12": {"skip": True}}
