"""Part types beyond A/B: S/O mapped onto make/buy, phantoms passed through,
mistyped parts corrected and listed for MAX."""

from datetime import date

import pandas as pd

from pkmrp.core.atp import promise
from pkmrp.core.netting import Demand, Part, Peg, plan
from pkmrp.core.part_types import normalize
from pkmrp.core.settings import PlanSettings

TODAY = date(2026, 11, 16)  # a Monday
S = PlanSettings()


def peg(ref="SO 1/01", root="SYS"):
    return (Peg("so", ref, root, (root,), 1000.0),)


def parts_df(rows):
    return pd.DataFrame(rows, columns=["part", "type", "description"])


def test_s_plans_as_make_and_o_as_buy_keeping_maxs_type():
    df, fixes = normalize(parts_df([("GUIDE", "S", ""), ("CABLE", "O", ""), ("TUBE", "Y", "")]), S)
    got = dict(zip(df["part"], df["type"], strict=True))
    assert got == {"GUIDE": "A", "CABLE": "B", "TUBE": "Y"}
    assert list(df["max_type"]) == ["S", "O", "Y"] and fixes == []


def test_override_corrects_a_mistyped_part_and_lists_it_until_max_matches():
    s = PlanSettings(type_overrides=(("CORD", "B", "bought, not built"),))
    df, fixes = normalize(parts_df([("CORD", "A", "POWER CORD")]), s)
    assert df.loc[0, "type"] == "B"
    assert fixes == [{"part": "CORD", "description": "POWER CORD", "max_type": "A",
                      "planned_as": "B", "why": "bought, not built"}]
    df, fixes = normalize(parts_df([("CORD", "B", "POWER CORD")]), s)  # MAX fixed
    assert df.loc[0, "type"] == "B" and fixes == []
    assert normalize(parts_df([("OTHER", "A", "")]), s)[1] == []  # not in MAX: skipped


def test_phantom_passes_demand_to_its_parts_on_the_parents_date():
    parts = {
        "SYS": Part("SYS", "A", mfg_lt=10),
        "KIT": Part("KIT", "P", mfg_lt=22),  # MAX keys a lead on some phantoms
        "PLATE": Part("PLATE", "A", mfg_lt=5),
        "BOLT": Part("BOLT", "B", purchase_lt=5),
    }
    kids = {"SYS": [("KIT", 1.0)], "KIT": [("PLATE", 1.0), ("BOLT", 4.0)]}
    r = plan(parts, kids, [Demand("SYS", date(2027, 1, 15), 2, peg("SO 9/01"), "so")],
             {"KIT": 1}, [], S, TODAY)
    sys_make = next(o for o in r.planned if o.part == "SYS")
    plate = next(o for o in r.planned if o.part == "PLATE")
    bolt = next(o for o in r.planned if o.part == "BOLT")
    assert not any(o.part == "KIT" for o in r.planned)  # never ordered itself
    # one kit on the shelf covers one; the other passes through, no lead of its own
    assert plate.qty == 1 and plate.need_by == sys_make.place_by
    assert bolt.qty == 4 and bolt.need_by == sys_make.place_by
    assert bolt.pegs[0].path == ("SYS", "KIT", "BOLT")
    assert "short_unplanned_type" not in {e.kind for e in r.exceptions}


def test_phantom_with_no_bom_is_flagged_not_ordered():
    r = plan({"KIT": Part("KIT", "P")}, {}, [Demand("KIT", date(2027, 1, 4), 1, peg(), "so")],
             {}, [], S, TODAY)
    assert r.planned == [] and [e.kind for e in r.exceptions] == ["make_without_bom"]


def test_promise_through_a_phantom_waits_only_for_its_parts():
    parts = {"KIT": Part("KIT", "P", mfg_lt=22), "BOLT": Part("BOLT", "B", purchase_lt=5)}
    out = promise("KIT", 1, TODAY, {"KIT": [("BOLT", 1.0)]}, {}, parts, lambda p: 5, TODAY)
    assert out["date"] == date(2026, 11, 23)  # 5 business days for the bolt, nothing more
