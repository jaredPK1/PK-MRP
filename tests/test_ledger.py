"""db/store.py + ledger/decisions.py on SQLite, the same tables PK_Ops gets."""

from datetime import date, datetime

import pandas as pd
import pytest
from sqlalchemy import create_engine, func, select

from pkmrp.core.netting import Exception_, PlanResult, Receipt
from pkmrp.core.settings import PlanSettings
from pkmrp.db import store
from pkmrp.ledger.decisions import inputs_hash, record


@pytest.fixture
def engine():
    e = create_engine("sqlite://")
    store.metadata.create_all(e)
    return e


def fake(qty=25.0, with_expedite=True):
    result = PlanResult()
    if with_expedite:
        result.exceptions.append(
            Exception_(
                "46-0020-01G",
                "expedite_open_po",
                ref="PO 70110162/01/01",
                days=110,
                qty=15,
                detail="due 2026-11-24, 15 needed from 2026-08-06",
            )
        )
    result.exceptions.append(Exception_("X", "unknown_part"))  # not a ledger kind
    run = {
        "today": date(2026, 10, 28),
        "settings": PlanSettings(),
        "result": result,
        "so_lines": pd.DataFrame(
            {
                "so": ["1"],
                "line": ["01"],
                "part": ["SYS"],
                "qty_due": [1.0],
                "cus_due": [pd.Timestamp("2026-12-01")],
            }
        ),
        "receipts": [Receipt("46-0020-01G", date(2026, 11, 24), 15, "po", "PO 70110162/01/01")],
        "stock": {"46-0020-01G": 0.0},
        "counts": {},
        "timings": {},
        "segments": [{"part": "46-0020-01G", "segment": "committed"}],
    }
    snap = {
        "buys": [
            {
                "part": "46-0020-01G",
                "qty": qty,
                "need_by": "2026-12-09",
                "place_by": "2026-08-20",
                "lead_days": 105,
                "lead_source": "PURLT_01",
                "orders": 7,
                "order_value": 12.2e6,
                "sales_orders": ["20048246"],
                "for_parts": ["SYS"],
                "pegs": [{"ref": "SO 20048246/05"}],
                "vendor": "IDEX",
            }
        ]
    }
    return run, snap


def count(engine, table, *where):
    with engine.connect() as c:
        return c.execute(select(func.count()).select_from(table).where(*where)).scalar()


def test_first_run_records_buys_and_ledger_kinds_only(engine):
    out = record(engine, *fake(), now=datetime(2026, 10, 28, 6))
    assert (out["new"], out["closed"], out["open"]) == (2, 0, 2)
    with engine.connect() as c:
        kinds = sorted(r.kind for r in c.execute(select(store.recommendation)))
        assert kinds == ["buy", "expedite"]
        row = c.execute(
            select(store.recommendation).where(store.recommendation.c.kind == "buy")
        ).one()
        assert row.segment == "committed" and row.mode == "shadow" and "20048246" in row.why_json


def test_repeating_an_unchanged_plan_adds_nothing(engine):
    record(engine, *fake(), now=datetime(2026, 10, 28, 6))
    out = record(engine, *fake(), now=datetime(2026, 10, 28, 7))
    assert (out["new"], out["closed"]) == (0, 0)
    assert count(engine, store.recommendation) == 2 and count(engine, store.run) == 2


def test_changed_and_vanished_recommendations_close_and_reopen(engine):
    record(engine, *fake(), now=datetime(2026, 10, 28, 6))
    out = record(engine, *fake(qty=30.0, with_expedite=False), now=datetime(2026, 10, 28, 7))
    assert (out["new"], out["closed"], out["open"]) == (1, 2, 1)
    closed = count(engine, store.recommendation, store.recommendation.c.closed_run_id.is_not(None))
    assert closed == 2


def test_inputs_hash_moves_with_inputs():
    a, _ = fake()
    b, _ = fake()
    assert inputs_hash(a) == inputs_hash(b)
    b["stock"] = {"46-0020-01G": 5.0}
    assert inputs_hash(a) != inputs_hash(b)


def test_ddl_is_sql_server_and_every_table_is_prefixed():
    stmts = store.ddl("mssql")
    creates = [s for s in stmts if s.startswith("CREATE TABLE")]
    assert len(creates) == len(store.metadata.tables) == 6
    assert all("mrp_" in s.split("(")[0] for s in creates)
    assert any("IDENTITY" in s for s in creates) and any("NVARCHAR(max)" in s for s in creates)


def test_missing_tables_reports_what_the_dba_has_not_run():
    e = create_engine("sqlite://")
    assert sorted(store.missing_tables(e)) == sorted(store.metadata.tables)


def test_segment_history_records_changes_only(engine):
    run, snap = fake()
    record(engine, run, snap, now=datetime(2026, 10, 28, 6))
    record(engine, run, snap, now=datetime(2026, 10, 28, 7))
    assert count(engine, store.segment_history) == 1
    run2, snap2 = fake()
    run2["today"] = date(2026, 10, 29)
    run2["segments"] = [{"part": "46-0020-01G", "segment": "order_driven"}]
    out = record(engine, run2, snap2, now=datetime(2026, 10, 29, 6))
    assert out["segments_changed"] == 1 and count(engine, store.segment_history) == 2
