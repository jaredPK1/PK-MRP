"""core/fix_max.py: what in MAX still names an ECN-obsoleted part."""

from datetime import date

import pandas as pd

from pkmrp.core.fix_max import bulk_rows, worklist
from pkmrp.core.netting import Part
from pkmrp.db.erp import check_read_only
from pkmrp.db.extract import ECN_RELEASES_SQL, MS_REQ_SQL

TODAY = date(2026, 10, 29)
T = pd.Timestamp


def ecn_rows():
    return pd.DataFrame({
        "part": ["00-2930-00G", "64-2694-02G", "45-3036-00G", "00-2853-01G", "97-2382-00"],
        "ecn": ["126056", "126056", "126041", "126168", "126056"],
        "status": ["Closed", "Closed", "Closed", "In Process", "Closed"],
        "originator": ["Abhi", "Abhi", "Ben", "Abhi", "Abhi"],
        "opened": [T("2026-03-31")] * 5,
        "closed": [T("2026-09-03"), T("2026-09-03"), T("2026-05-27"), None, T("2026-09-03")],
        "old_rev": ["C", "A", "B", "A", "A"], "new_rev": ["ZZ"] * 5,
        "change": ["Obsolete"] * 5, "summary": [""] * 5, "blocker": [""] * 5,
    })


def test_worklist_finds_orders_forecasts_wos_boms_and_coming_soon():
    releases = pd.DataFrame({"obsolete": ["00-2930-00G", "64-2694-02G", "00-2930-00G"],
                             "released": ["00-2930-01G", "64-2694-03G", "NOT-IN-MAX"],
                             "ecn": ["126056"] * 3})
    so = pd.DataFrame({
        "so": ["20047755", "20047026", "20048000", "20049999"], "line": ["20", "05", "01", "01"],
        "delivery": ["01"] * 4, "part": ["00-2930-00G", "00-2930-00G", "LENS", "00-2853-01G"],
        "customer": ["FiberHome", "", "Acme", "OFS"], "customer_id": ["FFOT", "PIR", "AC", "OFS"],
        "qty_due": [1.0, 1.0, 2.0, 1.0],
        "cur_due": [T("2026-10-29"), T("2034-12-29"), T("2026-11-01"), T("2034-12-29")],
    })
    wo = pd.DataFrame({"wo": ["50081327"], "parent": ["06-2322-01G"], "part": ["45-3036-00G"],
                       "qty_open": [3.0], "due": [T("2026-10-09")]})
    ms = pd.DataFrame({"ms": ["30003080"], "parent": ["2880-FAMILY"], "reference": ["FUJIKURA"],
                       "part": ["00-2930-00G"], "req_order": ["30003080"], "line": ["00"],
                       "delivery": ["00"], "qty_open": [2.0], "due": [T("2027-04-01")]})
    children = {"00-2853-01G": [("64-2694-02G", 1.0), ("97-2382-00", 1.0)],
                "OLD-KIT": [("45-3036-00G", 1.0)],
                "00-2930-00G": [("64-2694-02G", 1.0)]}
    parts = {p: Part(p, "B", description=p) for p in
             ("00-2930-00G", "00-2930-01G", "64-2694-02G", "64-2694-03G", "45-3036-00G",
              "00-2853-01G", "LENS", "06-2322-01G")}
    rules = {"64-2694-02G": {"part": "64-2694-03G"}}
    fx = worklist(ecn_rows(), releases, so, wo, ms, children, {"00-2853-01G", "00-2930-00G"},
                  parts, rules, TODAY)

    assert [r["so"] for r in fx["so_lines"]] == ["20047755", "20047026"]
    assert fx["so_lines"][0]["suggest"] == ["00-2930-01G"]  # not-in-MAX dropped
    assert fx["so_lines"][1]["unscheduled"] and fx["counts"]["so_scheduled"] == 1
    assert fx["ms_entries"][0]["planning_bill"] == "2880-FAMILY"
    assert fx["work_orders"][0]["suggest"] == [] and fx["work_orders"][0]["wo"] == "50081327"
    # live parent with demand keeps its BOM row; an obsolete parent's BOM, and
    # an obsoleted drawing (97-), are noise
    assert [(b["parent"], b["planned_as"]) for b in fx["boms"]] == [("00-2853-01G", "64-2694-03G")]
    assert [r["so"] for r in fx["coming"]] == ["20049999"]
    rows = bulk_rows(fx)
    assert rows[0][:6] == ["SO line", "20047755", "20", "01", "00-2930-00G", "00-2930-01G"]
    assert {r[0] for r in rows} == {"SO line", "MS entry", "Work order"}


def test_the_new_queries_pass_the_read_only_guard():
    check_read_only(MS_REQ_SQL)
    check_read_only(ECN_RELEASES_SQL)
