"""core/ecn.py and the pk_ecn query's read-only guard (pages: test_rank_web)."""

import pandas as pd

from pkmrp.core.ecn import by_part, obsolete_buys
from pkmrp.db.erp import check_read_only
from pkmrp.db.extract import ECN_PARTS_SQL


def _rows():
    return pd.DataFrame(
        {
            "part": ["64-2694-02G", "00-2930-00G", "00-2853-01G", "00-2853-01G", "ZZZ"],
            "ecn": ["126056", "126056", "126168", "126170", "1"],
            "status": ["Closed", "Closed", "In Process", "Out for Approval", "Closed"],
            "originator": ["Abhi", "Abhi", "Abhi", "Justin", "x"],
            "opened": pd.to_datetime(["2026-03-31", "2026-03-31", "2026-10-26", "2026-10-26", None]),
            "closed": pd.to_datetime(["2026-09-03", "2026-09-03", None, None, None]),
            "old_rev": ["A", "C", "A", "A", ""],
            "new_rev": ["ZZ", "ZZ", "ZZ", "B", "ZZ"],
            "change": ["Obsolete", "Obsolete", "Obsolete", "", ""],
            "summary": ["HUB swap", "HUB swap", "Obsolete 00-2853-01G", "", ""],
            "blocker": ["", "", "", "", ""],
        }
    )


def test_by_part_splits_open_from_obsolete_and_keeps_only_plan_parts():
    out = by_part(_rows(), {"64-2694-02G", "00-2930-00G", "00-2853-01G"})
    assert set(out) == {"64-2694-02G", "00-2930-00G", "00-2853-01G"}
    assert out["64-2694-02G"]["obsolete"]["ecn"] == "126056" and not out["64-2694-02G"]["open"]
    assert out["64-2694-02G"]["obsolete"]["closed"] == "2026-09-03"
    assert [e["ecn"] for e in out["00-2853-01G"]["open"]] == ["126170", "126168"]  # newest first
    assert out["00-2853-01G"]["obsolete"] is None


def test_obsolete_buys_name_what_pulls_them():
    parts = by_part(_rows(), {"64-2694-02G", "00-2930-00G", "00-2853-01G"})
    buys = [
        {"part": "64-2694-02G", "description": "SUPPORT", "qty": 32, "order_value": 7.4e6,
         "orders": 4, "story": {"goes_into": [{"part": "00-2930-00G", "units": 96}]}},
        {"part": "LENS", "qty": 1, "order_value": 9e6},
    ]
    rows = obsolete_buys(buys, parts)
    assert [r["part"] for r in rows] == ["64-2694-02G"]
    assert rows[0]["via"][0] == {"part": "00-2930-00G", "description": "", "units": 96,
                                 "obsolete": True, "open_ecns": []}


def test_the_ecn_query_passes_the_read_only_guard():
    check_read_only(ECN_PARTS_SQL)  # raises if it would write


def test_snapshot_keeps_ecns_for_plan_parts_and_reports_no_access():
    from types import SimpleNamespace

    from pkmrp.snapshot import _ecn

    run = {
        "ecn": {"status": "ok", "rows": _rows()},
        "result": SimpleNamespace(demands={"64-2694-02G": []}),
        "stock": {"00-2930-00G": 3.0, "00-2853-01G": 0.0},
        "open_pos": pd.DataFrame({"part": []}),
        "committed_plans": [],
    }
    buys = [{"part": "64-2694-02G", "qty": 32, "order_value": 1.0, "orders": 1,
             "story": {"goes_into": [{"part": "00-2930-00G", "units": 96}]}}]
    out = _ecn(run, buys, [])
    assert set(out["parts"]) == {"64-2694-02G", "00-2930-00G"}  # no stock, no demand: left out
    assert out["obsolete_parts"] == 2 and out["obsolete_buys"][0]["via"][0]["obsolete"]
    assert _ecn({"ecn": {"status": "no_access", "error": "4060", "rows": None}}, [], []) == {
        "status": "no_access", "error": "4060"}
