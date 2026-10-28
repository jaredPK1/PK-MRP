"""db/extract.py: every query passes the guard, and results come back clean."""

import datetime as dt

import pandas as pd
import pytest

from pkmrp.db import extract
from pkmrp.db.erp import check_read_only


@pytest.mark.parametrize("name", sorted(extract.ALL_SQL))
def test_every_extract_query_is_read_only(name):
    check_read_only(extract.ALL_SQL[name])


class FakeErp:
    """Returns a canned frame and records what was asked."""

    def __init__(self, frame):
        self.frame = frame
        self.calls = []

    def query(self, sql, params=None):
        self.calls.append((sql, params))
        return self.frame.copy()


def test_open_definitions_are_status_3():
    assert "STATUS_10 = '3'" in extract.OPEN_PO_SQL
    assert "STATUS_10 = '3'" in extract.OPEN_WO_SQL
    assert "STATUS_10 = '3'" in extract.WO_REQ_SQL
    assert "STATUS_28 = '3'" in extract.OPEN_SO_SQL and "STATUS_27 = '3'" in extract.OPEN_SO_SQL


def test_requirements_join_on_internal_order():
    assert "o.ORDER_10 = rd.ORDER_11" in extract.WO_REQ_SQL


def test_bom_takes_latest_effective_row_and_skips_family_bills():
    sql = extract.BOM_SQL
    assert "ORDER BY EFFDTE_02 DESC" in sql and "rn = 1" in sql
    assert "NOT LIKE '%-FAMILY'" in sql


def test_cost_is_per_stocking_unit():
    assert "COST_01 / CSTCNV_01" in extract.PARTS_SQL


def test_clean_types_dates_numbers_and_text():
    raw = pd.DataFrame(
        {
            "po": ["70110162"],
            "line": ["01"],
            "delivery": ["00"],
            "part": ["46-0020-01G"],
            "vendor_id": ["1234"],
            "buyer": ["RB"],
            "created": [dt.datetime(2026, 3, 2)],
            "org_due": ["2026-07-01"],
            "cur_due": [None],
            "qty_ordered": ["25"],
            "qty_current": [25],
            "qty_due": [25.0],
        }
    )
    df = extract.open_pos(FakeErp(raw))
    assert pd.api.types.is_datetime64_any_dtype(df["org_due"])
    assert pd.isna(df.loc[0, "cur_due"])
    assert df["qty_ordered"].dtype == float and df.loc[0, "qty_ordered"] == 25.0
    assert df.loc[0, "line"] == "01"  # text stays text, leading zero kept


def test_po_history_passes_the_since_date():
    erp = FakeErp(pd.DataFrame({"po": [], "created": []}))
    extract.po_history(erp, dt.date(2024, 10, 28))
    assert erp.calls[0][1] == [dt.date(2024, 10, 28)]
