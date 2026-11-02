from datetime import date, timedelta

from pkmrp.core.eol import build, match, mpn_index, norm
from pkmrp.core.netting import Demand, Part, Peg

TODAY = date(2026, 10, 30)


def test_norm_and_match_ignore_punctuation_and_case():
    idx = mpn_index(
        [("30-0699-00SG", "OPA699ID"), ("45-3029-01G", "AD230-2.3G-TO5")], ["30-0699-00SG"]
    )
    assert norm("ad230 2.3g to5") == "AD23023GTO5"
    assert match(["opa699id", "AD230-2.3G-TO5"], idx) == {"30-0699-00SG", "45-3029-01G"}
    assert match(["3006990 0SG"], idx) == {"30-0699-00SG"}  # PK number itself


def test_ltb_quantity_cover_and_sources():
    parts = {"30-0699-00SG": Part("30-0699-00SG", "B", "IC, OPA699ID", unit_cost=5.26)}
    pegs = (Peg("so", "SO 20048246/01", "01-2300AG-07G"),)
    demands = {"30-0699-00SG": [Demand("30-0699-00SG", TODAY + timedelta(days=90), 40, pegs, "so")]}
    dist = {
        "30-0699-00SG": {
            "checked": "2026-10-29T10:00",
            "offers": [
                {
                    "source": "digikey",
                    "mpn": "OPA699ID",
                    "lifecycle": "obsolete",
                    "lifecycle_text": "Obsolete",
                }
            ],
        }
    }
    notices = [
        {
            "id": "m1",
            "received": "2026-10-20T08:00:00Z",
            "subject": "PDN OPA699",
            "sender": "ti",
            "web_link": "http://x",
            "notice": {
                "is_notice": True,
                "kind": "last_time_buy",
                "part_numbers": ["OPA699ID"],
                "last_order_date": "2026-12-15",
                "replacements": ["OPA699IDR"],
                "summary": "LTB Dec 15",
            },
        }
    ]
    out = build(
        dist,
        notices,
        [],
        [("30-0699-00SG", "OPA699ID")],
        parts,
        demands,
        {"30-0699-00SG": 66},
        {},
        {"30-0699-00SG": 40},
        TODAY,
    )
    it = out["items"][0]
    assert it["kind"] == "obsolete" and it["last_order"] == date(2026, 12, 15)
    assert it["days_left"] == 46 and it["replacements"] == ["OPA699IDR"]
    # booked 40 + 2 years at 40/yr beyond the booked year -> 40 + 80 - 40 = 80, less 66 on hand
    assert it["ltb_qty"] == 14 and it["systems"] == ["01-2300AG-07G"] and it["orders"] == 1
    assert {s["source"] for s in it["signals"]} == {"distributor", "email"}


def test_non_notice_email_is_ignored():
    out = build(
        {},
        [{"id": "x", "notice": {"is_notice": False, "part_numbers": ["A"]}}],
        [],
        [],
        {"A": Part("A", "B")},
        {},
        {},
        {},
        {},
        TODAY,
    )
    assert out["items"] == []


def _dist(part, asked, *offers):
    return {part: {"checked": "2026-11-01T10:00", "mpn": asked, "offers": list(offers)}}


def _offer(mpn, maker, life, src="mouser", sku=""):
    return {"source": src, "mpn": mpn, "maker": maker, "sku": sku, "lifecycle": life,
            "lifecycle_text": life.title()}


def _one(dist, rows, booked=10, stock=0, part="P"):
    parts = {part: Part(part, "B", "THING", unit_cost=2.0)}
    demands = {part: [Demand(part, TODAY + timedelta(days=30), booked, (), "so")]} if booked else {}
    return build(dist, [], [], rows, parts, demands, {part: stock}, {}, {part: booked}, TODAY)["items"]


def test_maker_must_match_what_max_has_on_file():
    # a Mouser search for Edmund's 45-803 also finds a Wiha screwdriver
    rows = [("46-0126-00G", "45-803", "EDMUND OPTICS", "mpn_file")]
    wiha = _dist("46-0126-00G", "45-803", _offer("45803", "Wiha", "obsolete"))
    assert _one(wiha, rows, part="46-0126-00G") == []
    edmund = _dist("46-0126-00G", "45-803", _offer("45-803", "Edmund Optics Inc", "obsolete"))
    assert _one(edmund, rows, part="46-0126-00G")[0]["kind"] == "obsolete"


def test_number_must_match_exactly_and_short_numbers_need_a_maker():
    rows = [("93-0057-00G", "5763", "", "vendor_sku")]
    longer = _dist("93-0057-00G", "5763", _offer("57634 SL002", "Alpha Wire", "obsolete"))
    assert _one(longer, rows, part="93-0057-00G") == []
    bare = _dist("93-0057-00G", "5763", _offer("5763", "Festo", "obsolete"))
    assert _one(bare, rows, part="93-0057-00G") == []  # all digits, no maker on file


def test_asked_by_distributor_sku_is_one_product():
    rows = [("38-3001-00G", "926-1206-ND", "", "vendor_sku")]
    dk = _dist("38-3001-00G", "926-1206-ND",
               _offer("430278-507", "Tark Thermal Solutions", "obsolete", "digikey", "926-1206-ND"))
    assert _one(dk, rows, part="38-3001-00G")[0]["tier"] == "act"


def test_maker_names_alias_and_noise():
    from pkmrp.core.eol import maker_match

    assert maker_match("Same Sky (Formerly CUI Devices)", "CUI")
    assert maker_match("Amphenol ICC (FCI)", "AMPHENOL FCI")
    assert maker_match("Texas Instruments", "TI") and maker_match("onsemi", "ON SEMICONDUCTOR")
    assert not maker_match("Pulse Electronics", "PIC DESIGN")
    assert not maker_match("Thorlabs Optics", "EDMUND OPTICS")


def test_discontinued_at_distributor_is_not_obsolete():
    from pkmrp.integrations.distributors import normalize_lifecycle

    assert normalize_lifecycle("Discontinued at DigiKey") == "dist_dropped"
    assert normalize_lifecycle("Not For New Designs") == "nrnd"
    assert normalize_lifecycle("Discontinued") == "obsolete"


def test_tiers_and_an_active_alternate_means_switch_not_stockpile():
    rows = [("34-2579-00G", "68683-305LF", "AMPHENOL FCI", "mpn_file"),
            ("34-2579-00G", "76342-305LF", "AMPHENOL FCI", "mpn_file"),
            ("34-2579-00G", "SEE PART NOTES", "X", "mpn_file")]
    dist = _dist("34-2579-00G", "68683-305LF", _offer("68683-305LF", "Amphenol ICC (FCI)", "obsolete"))
    it = _one(dist, rows, part="34-2579-00G")[0]
    assert it["tier"] == "act" and [a["mpn"] for a in it["alternates"]] == ["76342-305LF"]
    assert it["alternates"][0]["status"] == "unchecked"
    dist["34-2579-00G"]["alts"] = {"76342-305LF": {"checked": "2026-11-01T11:00", "offers": [
        _offer("76342-305LF", "Amphenol ICC (FCI)", "active")]}}
    it = _one(dist, rows, part="34-2579-00G")[0]
    assert it["alt_active"] and it["tier"] == "watch"
    assert _one(dist, rows, booked=0, part="34-2579-00G")[0]["tier"] == "fyi"
    covered = _dist("34-2579-00G", "68683-305LF", _offer("68683-305LF", "Amphenol FCI", "obsolete"))
    assert _one(covered, rows, stock=500, part="34-2579-00G")[0]["tier"] == "watch"
