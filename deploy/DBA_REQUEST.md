# PK-MRP on PK-SQL01 — what we need

Chris,

Two short scripts for PK-MRP (the new backlog-driven buying app). Both are in
this folder; run them in either order.

## 1. `pk_ops_schema.sql` — PK-MRP's tables in PK_Ops

PK-MRP keeps a small **Decision Ledger** in PK_Ops: every buy, expedite or
push-out it recommends, so after a few weeks in shadow mode we can put its
advice beside what buyers actually did.

- 6 tables, all prefixed `mrp_`; nothing of PK Dispatch's is touched.
- **No grants needed.** The app logs in as `app_control_tower`, which is already
  `db_datareader` + `db_datawriter` on PK_Ops (checked 2026-10-28).
- **Size:** a few hundred rows a day. An unchanged recommendation is stored once,
  not on every hourly run.

## 2. `pk_sales_read_grant.sql` — read the Book/Bill 2.0 pipeline

PK-MRP turns open Book/Bill bookings into probability-weighted demand for the
~119 long-lead parts it plans a year ahead — the same rows the Book/Bill 2.0
forecast already uses.

- **Read-only:** `SELECT` on five tables — `bookings`, `accounts`,
  `booking_line_items`, `booking_line_item_options`, `products`.
- `app_control_tower` has no user in `pk_sales` today (it gets error 916), so the
  script creates one first if it isn't there.

## After either one

Nothing to restart. PK-MRP picks each up on its next hourly run — its footer
changes from "waiting on its PK_Ops tables" to "recording", and the Committed
page starts showing pipeline demand.

The app never runs DDL itself (its login can't), so any future schema change
will come the same way: a regenerated script and a note like this one.

— Jared
