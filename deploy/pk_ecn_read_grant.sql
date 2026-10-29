-- PK-MRP: read ECNs from Ron's ECN app (pk_ecn on PK-SQL01).
-- Read-only, two tables, for the app login PK-MRP already uses.
-- PK-MRP shows open ECNs and ECN-obsoleted parts (new rev ZZ) next to every
-- part it recommends, and alerts on buys of obsoleted parts. It links to the
-- ECN app (/ecn/?pn=<part>) for the detail; it never writes to pk_ecn.

USE pk_ecn;
GO

IF NOT EXISTS (SELECT 1 FROM sys.database_principals WHERE name = 'app_control_tower')
    CREATE USER app_control_tower FOR LOGIN app_control_tower;
GO

GRANT SELECT ON dbo.ecn      TO app_control_tower;
GRANT SELECT ON dbo.ecn_part TO app_control_tower;
GO
