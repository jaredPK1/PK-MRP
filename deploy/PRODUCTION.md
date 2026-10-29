# PK-MRP on .80 (production)

.70 is the build-and-test copy; .80 is production. Both hosts point at the
same PK-SQL01 databases -- including **PK_Ops**, where PK-MRP keeps its
Decision Ledger, notes, holds, replacements, Done log, overbuy clears and
settings. So everything people *enter* is already shared; the only thing that
must run on exactly one host is the planner loop's **writes** (ledger
recording, the Done-vs-MAX check, the Friday email). That is
`SCHEDULER_ENABLED`: **1 on production only**.

## Before the first push (on .70)

1. `env/pk-mrp.env` has every key in `apps/pk-mrp/env.template`
   (`scripts/check-env.py`), including `PK_NOTIFY_TOKEN` (the weekly email).
2. PK-MRP `main` is pushed to GitHub (push-to-80 refuses otherwise).
3. Tests pass: `docker run --rm -v "$PWD":/app -w /app python:3.11-slim sh -c "pip install -e . pytest && pytest -q"`.
4. The DBA grants are in (same login, same server, so they already apply to .80):
   PK_Ops `mrp_*` tables, pk_sales read, **pk_ecn read** (`deploy/pk_ecn_read_grant.sql`).

## The push

Server Manager portal (https://10.6.1.70/), signed in with GitHub ->
PK-MRP -> **Push to .80**. (`scripts/push-to-80.sh pk-mrp --dry-run` first if
you want to see what it will do; it is read-only on both hosts.)

First push bootstraps .80 from .70: compose block, `pk-mrp-data` volume,
apps.json entry, Caddy route `/pk-mrp/*`, and an env file seeded from .70's
(10.6.1.70 -> .80 rewritten, so `APP_BASE_URL` becomes .80's;
`SCHEDULER_ENABLED` seeded **0**). An existing .80 env file is never touched.

## Right after the push

1. **Permissions (prod DB is separate):** https://10.6.1.80/admin/permissions
   -> add the `pk-mrp` app row if missing, then grants. Today on .70: Jared
   admin; Chad, Aaron, Rob viewers. Johnny has no grant yet.
2. **Health:** https://10.6.1.80/pk-mrp/ loads after sign-in; the first plan
   appears within ~1 minute (the loop plans at start, then hourly).
3. **Cutover the writes** (one host only -- do both in the same few minutes):
   - .80 `env/pk-mrp.env`: `SCHEDULER_ENABLED=1`, then
     `docker compose up -d pk-mrp` on .80.
   - .70 `env/pk-mrp.env`: `SCHEDULER_ENABLED=0`,
     `DEV_ALLOWED_EMAILS=jared.green@pkinetics.com,chris.luetjen@pkinetics.com,mark.berezny@pkinetics.com`,
     `PROD_URL=https://10.6.1.80/pk-mrp`, then `docker compose up -d pk-mrp`.
   - Check: .80 footer says "Decision ledger recording"; .70 footer says
     "Test copy — the ledger records on production"; anyone else opening
     .70 gets a page pointing at .80.
4. **Launcher tile** on .80's PK Connect (portal image template -- the
   `{% elif app.name == 'pk-mrp' %}` icon lives in pk-server-manager's
   `server-manager/templates/index.html`).
5. **Optional history:** `data/history/*.json` and `data/trend.json` live in
   .70's `pk-mrp-data` volume only. Copy them to .80's volume if the
   Analytics trend and "came off the list since" should continue unbroken;
   otherwise they restart from the first .80 plan.

## Rolling back

Set .80 `SCHEDULER_ENABLED=0` and .70 `SCHEDULER_ENABLED=1` (clear
`DEV_ALLOWED_EMAILS`) -- no data moves, because PK_Ops is shared.
