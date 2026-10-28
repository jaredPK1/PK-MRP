"""The read-only guard in db/erp.py (CLAUDE.md hard rule 1)."""

import pytest

from pkmrp.config import DbConfig
from pkmrp.db.erp import ErpClient, ReadOnlyViolation, check_read_only

ALLOWED = [
    "SELECT 1",
    "select PRTNUM_01 from Part_Master",
    "  \n\tSELECT TOP 5 * FROM Order_Master WHERE TYPE_10 = 'PO'",
    "WITH o AS (SELECT * FROM Order_Master) SELECT COUNT(*) FROM o",
    "SELECT 1;",
    "-- open POs\nSELECT * FROM Order_Master WHERE STATUS_10 = '3'",
    "/* header */ SELECT 1",
    # Keywords inside literals and quoted identifiers are data, not code.
    "SELECT * FROM Part_Master WHERE PMDES1_01 LIKE '%DELETE%'",
    "SELECT 'it''s; DROP TABLE x' AS note",
    "SELECT [UPDATE] FROM t",
    "SELECT N'INSERT' AS n",
    # Column names that merely contain a keyword.
    "SELECT DELNUM_10, CREDTE_10, UPDATED_AT FROM Order_Master",
    "SELECT * FROM Part_Master WHERE PRTNUM_01 = ?",
]

REJECTED = [
    "",
    "   ",
    "INSERT INTO t VALUES (1)",
    "UPDATE Part_Master SET PURLT_01 = 10",
    "DELETE FROM Order_Master",
    "MERGE INTO t USING s ON 1=1 WHEN MATCHED THEN DELETE;",
    "TRUNCATE TABLE t",
    "DROP TABLE Part_Master",
    "ALTER TABLE t ADD c int",
    "CREATE TABLE t (c int)",
    "EXEC sp_who",
    "EXECUTE ('SELECT 1')",
    "sp_executesql N'SELECT 1'",
    # Starts with SELECT but is not read-only.
    "SELECT 1; DELETE FROM Order_Master",
    "SELECT 1; SELECT 2",
    "SELECT * INTO #t FROM Part_Master",
    "SELECT * INTO backup_pm FROM Part_Master",
    "WITH x AS (SELECT 1 AS a) UPDATE Part_Master SET PURLT_01 = 1",
    "WITH x AS (SELECT 1 AS a) DELETE FROM Part_Master",
    "SELECT * FROM OPENROWSET('SQLNCLI', 'srv', 'SELECT 1')",
    "SELECT * FROM OPENQUERY(lnk, 'SELECT 1')",
    "SELECT xp_cmdshell('dir')",
    "SELECT 1 WAITFOR DELAY '00:00:10'",
    # Comments can't hide a statement, and can't hide the start.
    "/* SELECT */ DELETE FROM t",
    "-- SELECT\nDELETE FROM t",
    "SELECT 1 /* ok */; DROP TABLE t",
    "SELECT 1 /* unterminated",
    "SELECT 'unterminated",
    # Batches that set things up first.
    "SET NOCOUNT ON; SELECT 1",
    "DECLARE @x int = 1; SELECT @x",
    "USE PK_Ops; SELECT 1",
]


@pytest.mark.parametrize("sql", ALLOWED)
def test_allows_single_read_only_queries(sql):
    assert check_read_only(sql) == sql


@pytest.mark.parametrize("sql", REJECTED)
def test_rejects_anything_that_could_write_or_chain(sql):
    with pytest.raises(ReadOnlyViolation):
        check_read_only(sql)


def test_rejects_non_strings():
    with pytest.raises(ReadOnlyViolation):
        check_read_only(None)


class _Boom:
    """A connect() that fails the test if anything reaches it."""

    calls = 0

    def __call__(self, conn_str):
        _Boom.calls += 1
        raise AssertionError("the guard should have stopped this before connecting")


def test_client_checks_before_connecting():
    client = ErpClient("unused", connect=_Boom())
    with pytest.raises(ReadOnlyViolation):
        client.query("UPDATE Part_Master SET PURLT_01 = 1")
    assert _Boom.calls == 0


class _FakeCursor:
    description = [("PRTNUM_01",), ("PURLT_01",)]

    def __init__(self, log):
        self.log = log

    def execute(self, sql, params):
        self.log.append((sql, params))

    def fetchall(self):
        return [("46-0020-01G", 90)]

    def close(self):
        pass


class _FakeConn:
    def __init__(self):
        self.log = []

    def cursor(self):
        return _FakeCursor(self.log)

    def close(self):
        pass


def test_client_returns_a_dataframe_for_allowed_sql():
    conn = _FakeConn()
    client = ErpClient("unused", connect=lambda s: conn)
    df = client.query(
        "SELECT PRTNUM_01, PURLT_01 FROM Part_Master WHERE PRTNUM_01 = ?", ["46-0020-01G"]
    )
    assert list(df.columns) == ["PRTNUM_01", "PURLT_01"]
    assert df.iloc[0]["PURLT_01"] == 90
    assert conn.log == [
        ("SELECT PRTNUM_01, PURLT_01 FROM Part_Master WHERE PRTNUM_01 = ?", ["46-0020-01G"])
    ]


def test_erp_connection_string_is_read_only_and_needs_credentials():
    cfg = DbConfig.from_env({"DB_USER": "app_control_tower", "DB_PASSWORD": "x"})
    s = cfg.erp_conn_str()
    assert "DATABASE=ExactMAXPKLive" in s and "ApplicationIntent=ReadOnly" in s
    assert "DATABASE=PK_Ops" in cfg.ops_conn_str()
    with pytest.raises(ValueError):
        DbConfig.from_env({}).erp_conn_str()
    assert "Trusted_Connection=yes" in DbConfig.from_env({"ERP_AUTH": "windows"}).erp_conn_str()
