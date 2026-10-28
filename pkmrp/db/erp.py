"""Read-only access to ExactMAX. The only module that imports pyodbc.

Three locks keep PK-MRP from ever writing to MAX:

  1. the login (app_control_tower) has SELECT only on ExactMAXPKLive;
  2. the connection asks for ApplicationIntent=ReadOnly;
  3. every statement passes check_read_only() before it reaches the driver.

The guard is deliberately stricter than "starts with SELECT": a batch that
starts with SELECT can still end in "; DELETE ...", and SELECT ... INTO
creates a table. It accepts exactly one statement that begins with SELECT
or WITH and contains no keyword that writes, runs code or reaches another
server. String literals and comments are blanked before checking, so a
part description containing "DELETE" can't trip it and a comment can't hide
a statement from it.
"""

import re

# Anything that changes data or schema, runs code, or reaches outside the
# database. INTO blocks SELECT ... INTO (it creates a table, temp or not).
FORBIDDEN = (
    "INSERT",
    "UPDATE",
    "DELETE",
    "MERGE",
    "TRUNCATE",
    "DROP",
    "ALTER",
    "CREATE",
    "EXEC",
    "EXECUTE",
    "GRANT",
    "REVOKE",
    "DENY",
    "INTO",
    "BULK",
    "OPENROWSET",
    "OPENQUERY",
    "OPENDATASOURCE",
    "DBCC",
    "BACKUP",
    "RESTORE",
    "SHUTDOWN",
    "KILL",
    "RECONFIGURE",
    "USE",
    "WAITFOR",
    "DECLARE",
    "SET",
)
_FORBIDDEN_RE = re.compile(r"\b(" + "|".join(FORBIDDEN) + r")\b", re.IGNORECASE)
# System procedures (sp_executesql, xp_cmdshell) even without EXEC in front.
_PROC_RE = re.compile(r"\b(sp|xp)_\w+", re.IGNORECASE)


class ReadOnlyViolation(ValueError):
    """Raised for any SQL the read-only guard will not send to ExactMAX."""


def _blank_literals_and_comments(sql):
    """The SQL with string literals, quoted identifiers' contents and
    comments replaced by spaces, so keyword checks see only real code."""
    out, i, n = [], 0, len(sql)
    while i < n:
        c = sql[i]
        if c == "-" and sql.startswith("--", i):
            j = sql.find("\n", i)
            j = n if j == -1 else j
            out.append(" " * (j - i))
            i = j
        elif c == "/" and sql.startswith("/*", i):
            j = sql.find("*/", i + 2)
            if j == -1:
                raise ReadOnlyViolation("Unterminated /* comment")
            out.append(" " * (j + 2 - i))
            i = j + 2
        elif c in "'\"[":
            close = "]" if c == "[" else c
            j = i + 1
            while True:
                j = sql.find(close, j)
                if j == -1:
                    raise ReadOnlyViolation("Unterminated quoted text")
                if sql.startswith(close * 2, j):  # '' or ]] escape
                    j += 2
                    continue
                break
            # Keep the quote marks so "N'x'" stays two tokens; blank the inside.
            out.append(c + " " * (j - i - 1) + close)
            i = j + 1
        else:
            out.append(c)
            i += 1
    return "".join(out)


def check_read_only(sql):
    """Return the SQL unchanged if it is a single read-only query; raise
    ReadOnlyViolation otherwise."""
    if not isinstance(sql, str) or not sql.strip():
        raise ReadOnlyViolation("Empty query")
    code = _blank_literals_and_comments(sql).strip()
    if code.endswith(";"):
        code = code[:-1].rstrip()
    if ";" in code:
        raise ReadOnlyViolation("Only one statement per query")
    first = re.match(r"[A-Za-z]+", code)
    if not first or first.group(0).upper() not in ("SELECT", "WITH"):
        raise ReadOnlyViolation("ExactMAX queries must start with SELECT or WITH")
    bad = _FORBIDDEN_RE.search(code)
    if bad:
        raise ReadOnlyViolation(f"{bad.group(1).upper()} is not allowed against ExactMAX")
    proc = _PROC_RE.search(code)
    if proc:
        raise ReadOnlyViolation(f"System procedure {proc.group(0)} is not allowed")
    return sql


class ErpClient:
    """A read-only connection to ExactMAXPKLive. query() returns a DataFrame.

    `connect` is injectable so tests never touch PK-SQL01.
    """

    def __init__(self, conn_str, timeout=60, connect=None):
        self._conn_str = conn_str
        self._timeout = timeout
        self._connect = connect
        self._conn = None

    def _connection(self):
        if self._conn is None:
            if self._connect is None:
                import pyodbc  # only import in the app

                self._conn = pyodbc.connect(
                    self._conn_str, timeout=self._timeout, autocommit=True, readonly=True
                )
            else:
                self._conn = self._connect(self._conn_str)
        return self._conn

    def query(self, sql, params=None):
        check_read_only(sql)  # first: before any import, connection or cursor
        import pandas as pd

        cur = self._connection().cursor()
        try:
            cur.execute(sql, params or [])
            cols = [d[0] for d in cur.description] if cur.description else []
            return pd.DataFrame.from_records([tuple(r) for r in cur.fetchall()], columns=cols)
        finally:
            cur.close()

    def close(self):
        if self._conn is not None:
            self._conn.close()
            self._conn = None
