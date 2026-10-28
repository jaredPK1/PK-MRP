# PK-MRP in PK_Ops — what we need

Chris,

PK-MRP (the new backlog-driven buying app) keeps a small **Decision Ledger** in
PK_Ops: every buy, expedite or push-out it recommends, so that after a few weeks
in shadow mode we can put its advice beside what buyers actually did.

**One thing to run:** `deploy/pk_ops_schema.sql`, once, in PK_Ops.

- 6 tables, all prefixed `mrp_`; nothing of PK Dispatch's is touched.
- **No grants needed.** The app logs in as `app_control_tower`, which is already
  `db_datareader` + `db_datawriter` on PK_Ops (checked 2026-10-28).
- **Size:** a few hundred rows a day. An unchanged recommendation is stored once,
  not on every hourly run.
- **Until it's run,** the app works normally and just shows "Decision ledger
  waiting on its PK_Ops tables" in its footer. It starts recording on the next
  hourly run after the tables exist; nothing to restart.

The app never runs DDL itself (its login can't), so any future schema change will
come the same way: a regenerated script and a note like this one.

— Jared
