-- PK-MRP: read the Book/Bill 2.0 pipeline in pk_sales (PK-SQL01).
-- Read-only, five tables, for the app login PK-MRP already uses.
-- PK-MRP turns open, forecast-on, no-SO-yet bookings into probability-
-- weighted demand for its ~119 long-lead "committed" parts. Same rows the
-- Book/Bill 2.0 forecast uses (pk-sales-app migration 081).

USE pk_sales;
GO

IF NOT EXISTS (SELECT 1 FROM sys.database_principals WHERE name = 'app_control_tower')
    CREATE USER app_control_tower FOR LOGIN app_control_tower;
GO

GRANT SELECT ON dbo.bookings                  TO app_control_tower;
GRANT SELECT ON dbo.accounts                  TO app_control_tower;
GRANT SELECT ON dbo.booking_line_items        TO app_control_tower;
GRANT SELECT ON dbo.booking_line_item_options TO app_control_tower;
GRANT SELECT ON dbo.products                  TO app_control_tower;
GO
