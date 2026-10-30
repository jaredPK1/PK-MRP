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
