"""PK-MRP's own state in PK_Ops: the Decision Ledger and settings.

One definition of every table, in SQLAlchemy Core. The DBA script
(deploy/pk_ops_schema.sql) is generated from it -- `pkmrp schema` -- so the
script and the code can't drift, and tests run the same tables on SQLite.

The app's login (app_control_tower) reads and writes rows in PK_Ops but has
no CREATE/ALTER there, so the app never runs DDL: a schema change is a new
generated script and a request to the DBA. Every table is prefixed mrp_
because PK_Ops is shared with PK Dispatch.

The ledger is append-only in spirit. A recommendation row is written once,
with a hash of its content and the why behind it, and never edited --
except to close it, when a later run no longer makes it. What people did
(POs placed, expedites, receipts) goes in mrp_outcome, matched from MAX.
"""

from sqlalchemy import (
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    UnicodeText,
    UniqueConstraint,
)
from sqlalchemy import Table as _Table

metadata = MetaData()


def Table(name, *cols, **kw):  # noqa: N802 -- reads like SQLAlchemy's
    assert name.startswith("mrp_"), "PK_Ops is shared: every PK-MRP table starts mrp_"
    return _Table(name, metadata, *cols, **kw)


run = Table(
    "mrp_run",
    Column("run_id", Integer, primary_key=True, autoincrement=True),
    Column("plan_date", Date, nullable=False),
    Column("started_at", DateTime, nullable=False),
    Column("finished_at", DateTime),
    Column("host", String(64)),
    Column("app_version", String(32)),
    # sha256 of the inputs that produced it (SO set, supply, parameters)
    Column("inputs_hash", String(64), nullable=False),
    Column("inputs_json", UnicodeText),  # counts, settings, timings -- not the data itself
    Column("status", String(16), nullable=False),  # ok | failed
    Index("ix_mrp_run_plan_date", "plan_date"),
)

recommendation = Table(
    "mrp_recommendation",
    Column("rec_id", Integer, primary_key=True, autoincrement=True),
    Column("run_id", Integer, ForeignKey("mrp_run.run_id"), nullable=False),
    Column("created_at", DateTime, nullable=False),
    # buy | expedite | push_out | cancel | beyond_backlog
    Column("kind", String(24), nullable=False),
    Column("part", String(32), nullable=False),
    Column("ref", String(48)),  # the PO line, for expedite / push-out / cancel
    Column("qty", Float),
    Column("need_by", Date),
    Column("place_by", Date),
    Column("lead_days", Float),
    Column("lead_source", String(48)),
    Column("segment", String(16)),  # committed | unproven_long | order_driven
    Column("mode", String(8), nullable=False),  # shadow | live (what buyers saw)
    Column("order_count", Integer),
    Column("order_value", Float),
    Column("why_json", UnicodeText),  # pegged SO lines, BOM paths, the ledger behind it
    Column("content_hash", String(64), nullable=False),
    Column("closed_run_id", Integer, ForeignKey("mrp_run.run_id")),
    Column("closed_at", DateTime),
    Column("closed_reason", String(64)),
    Index("ix_mrp_rec_open", "content_hash", "closed_run_id"),
    Index("ix_mrp_rec_part", "part", "kind"),
)

outcome = Table(
    "mrp_outcome",
    Column("outcome_id", Integer, primary_key=True, autoincrement=True),
    Column("rec_id", Integer, ForeignKey("mrp_recommendation.rec_id")),
    Column("observed_at", DateTime, nullable=False),
    # po_placed | po_expedited | po_pushed | po_cancelled | received | shipped
    Column("what", String(24), nullable=False),
    Column("part", String(32), nullable=False),
    Column("ref", String(48)),
    Column("qty", Float),
    Column("event_date", Date),
    Column("detail", UnicodeText),
    Index("ix_mrp_outcome_rec", "rec_id"),
    Index("ix_mrp_outcome_part", "part", "event_date"),
)

segment_history = Table(
    "mrp_segment_history",
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("effective_date", Date, nullable=False),
    Column("part", String(32), nullable=False),
    Column("segment", String(16), nullable=False),
    Column("p50_days", Integer),
    Column("p80_days", Integer),
    Column("reasons", UnicodeText),
    UniqueConstraint("effective_date", "part", name="uq_mrp_segment_day_part"),
)

settings = Table(
    "mrp_settings",
    Column("setting_key", String(64), primary_key=True),
    Column("setting_value", UnicodeText),
    Column("updated_at", DateTime, nullable=False),
    Column("updated_by", String(128), nullable=False),
)

part_class_mode = Table(
    "mrp_part_class_mode",
    # committed | order_driven | unproven_long, or a buyer code
    Column("part_class", String(32), primary_key=True),
    Column("mode", String(8), nullable=False),  # shadow | live -- Jared switches
    Column("updated_at", DateTime, nullable=False),
    Column("updated_by", String(128), nullable=False),
)


def ddl(dialect_name="mssql"):
    """CREATE TABLE / INDEX statements for the DBA, in dependency order."""
    from sqlalchemy.schema import CreateIndex, CreateTable

    if dialect_name == "mssql":
        from sqlalchemy.dialects import mssql

        # Render for a current SQL Server: DATE (not DATETIME) for dates and
        # NVARCHAR(max) (not the deprecated NTEXT) for long text.
        dialect = mssql.dialect(deprecate_large_types=True)
        dialect.server_version_info = (15, 0)
    else:
        from sqlalchemy.dialects import sqlite

        dialect = sqlite.dialect()
    out = []
    for t in metadata.sorted_tables:
        out.append(str(CreateTable(t).compile(dialect=dialect)).strip() + ";")
        for ix in sorted(t.indexes, key=lambda i: i.name):
            out.append(str(CreateIndex(ix).compile(dialect=dialect)).strip() + ";")
    return out


def missing_tables(engine):
    """Names of PK-MRP tables not present yet (the DBA script not run)."""
    from sqlalchemy import inspect

    # The DBA creates them in dbo, but app_control_tower's default schema in
    # pk_ops is db_datareader, and the inspector looks only in the default one.
    schema = "dbo" if engine.dialect.name == "mssql" else None
    have = set(inspect(engine).get_table_names(schema=schema))
    return [t for t in metadata.tables if t not in have]


def ops_engine(cfg):
    """A SQLAlchemy engine on PK_Ops from a DbConfig."""
    from urllib.parse import quote_plus

    from sqlalchemy import create_engine

    return create_engine(
        "mssql+pyodbc:///?odbc_connect=" + quote_plus(cfg.ops_conn_str()), pool_pre_ping=True
    )


def get_setting(engine, key, default=None):
    """A stored setting (JSON), or `default` when it was never set."""
    import json

    from sqlalchemy import select

    with engine.connect() as conn:
        row = conn.execute(
            select(settings.c.setting_value).where(settings.c.setting_key == key)
        ).first()
    return json.loads(row[0]) if row and row[0] else default


def put_setting(engine, key, value, by, now=None):
    """Store a setting (JSON), replacing what was there."""
    import json
    from datetime import datetime

    from sqlalchemy import delete, insert

    with engine.begin() as conn:
        conn.execute(delete(settings).where(settings.c.setting_key == key))
        conn.execute(
            insert(settings).values(
                setting_key=key,
                setting_value=json.dumps(value, sort_keys=True),
                updated_at=now or datetime.now(),
                updated_by=by,
            )
        )
