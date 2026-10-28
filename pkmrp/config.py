"""Environment for PK-MRP.

Connection settings come from the environment (a git-ignored .env locally,
pk-server-manager's governed env file when deployed). Planning settings --
horizons, thresholds, part-class modes -- will live in PK_Ops (mrp_settings)
so they are editable and attributed; only what is needed to reach the
databases is read here.
"""

import os
from dataclasses import dataclass

ODBC_DRIVER = "ODBC Driver 18 for SQL Server"


@dataclass(frozen=True)
class DbConfig:
    server: str
    port: str
    user: str
    password: str
    erp_database: str
    ops_database: str
    auth: str  # "sql" (deployed) or "windows" (laptop)

    @classmethod
    def from_env(cls, env=None):
        env = os.environ if env is None else env
        auth = (env.get("ERP_AUTH") or "sql").strip().lower()
        if auth not in ("sql", "windows"):
            raise ValueError(f"ERP_AUTH must be 'sql' or 'windows', not {auth!r}")
        return cls(
            server=env.get("DB_SERVER", "PK-SQL01"),
            port=env.get("DB_PORT", "1433"),
            user=env.get("DB_USER", ""),
            password=env.get("DB_PASSWORD", ""),
            erp_database=env.get("ERP_DATABASE", "ExactMAXPKLive"),
            ops_database=env.get("OPS_DATABASE", "PK_Ops"),
            auth=auth,
        )

    def _conn_str(self, database):
        parts = [
            f"DRIVER={{{ODBC_DRIVER}}}",
            f"SERVER={self.server},{self.port}",
            f"DATABASE={database}",
            "TrustServerCertificate=yes",
            "Encrypt=yes",
        ]
        if self.auth == "windows":
            parts.append("Trusted_Connection=yes")
        else:
            if not self.user or not self.password:
                raise ValueError("DB_USER and DB_PASSWORD are required when ERP_AUTH=sql")
            parts += [f"UID={self.user}", f"PWD={self.password}"]
        return ";".join(parts) + ";"

    def erp_conn_str(self):
        # ApplicationIntent is belt to the braces of the login (SELECT only on
        # ExactMAXPKLive) and of the guard in db/erp.py.
        return self._conn_str(self.erp_database) + "ApplicationIntent=ReadOnly;"

    def ops_conn_str(self):
        return self._conn_str(self.ops_database)
