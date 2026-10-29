"""The pkmrp command. Shadow mode only: it reads MAX and reports; it never
writes anywhere yet."""

from collections import Counter

import click

from .config import DbConfig
from .db.erp import ErpClient

VERSION = "0.2.0"

SHOWCASE = ("46-0020-01G", "04-1999-02G", "53-4104-00G", "31-7100-01SG")


@click.group()
def main():
    """PK-MRP: backlog-driven material planning (shadow mode)."""


def _erp():
    return ErpClient(DbConfig.from_env().erp_conn_str(), timeout=180)


def _fmt_part(run, part):
    res, info = run["result"], run["parts"].get(part)
    lt = run["lead_times"].get(part)
    lines = [f"\n=== {part}  {info.description if info else '(not in Part_Master)'}"]
    if info:
        lt_txt = (
            (
                f"realized median {lt['median']:g} / P80 {lt['p80']:g} bdays "
                f"[{lt['source']}], PURLT {info.purchase_lt:g}"
                + (f", ratio {lt['ratio']}" if lt and lt.get("ratio") else "")
            )
            if lt
            else f"PURLT {info.purchase_lt:g}"
        )
        lines.append(f"type {info.type} | on hand {run['stock'].get(part, 0):g} | {lt_txt}")
    lines.append("  ledger (date, qty, what, ref):")
    for when, qty, kind, ref in res.ledger.get(part, [])[:40]:
        lines.append(f"    {str(when or ''):10s} {qty:+9g}  {kind:14s} {ref}")
    for o in [o for o in res.planned if o.part == part][:15]:
        lines.append(
            f"  PLANNED {o.kind} {o.qty:g} need {o.need_by} place-by {o.place_by}"
            f"{'  LATE' if o.late else ''}  [{o.lead_days:g}d {o.lead_source}]"
            f"  for {', '.join(p.ref for p in o.pegs[:4])}"
            f"{' +' + str(len(o.pegs) - 4) if len(o.pegs) > 4 else ''}"
        )
    for e in [e for e in res.exceptions if e.part == part][:15]:
        lines.append(f"  EXCEPTION {e.kind} {e.ref} {e.detail}")
    return "\n".join(lines)


@main.command()
@click.option(
    "--part", "parts", multiple=True, help="Parts to show (default: the four showcase parts)."
)
def shadow(parts):
    """Run a full plan against live MAX and print shadow output."""
    from .run import build_plan

    run = build_plan(_erp())
    c, res = run["counts"], run["result"]
    click.echo(
        f"Plan for {run['today']}: {c['so_demand']} backlog lines planned of {c['so_lines']}, "
        f"{c['wo_requirements']} WO requirements, {c['receipts']} open receipts"
    )
    click.echo(
        f"  planned orders {c['planned']} "
        f"({Counter(o.kind for o in res.planned)}), late to place "
        f"{sum(1 for o in res.planned if o.late and o.kind == 'buy')}"
    )
    click.echo(f"  exceptions {Counter(e.kind for e in res.exceptions)}")
    click.echo(
        f"  worklists { ({k: len(v) for k, v in run['worklists'].items()}) }, "
        f"BOM rows skipped by type code {run['bom_codes_skipped']}, "
        f"cycle edges {len(res.cycle_edges)}"
    )
    click.echo(f"  timings {run['timings']}")
    for p in parts or SHOWCASE:
        click.echo(_fmt_part(run, p))


def _ledger(run, snap):
    """Record the run in the Decision Ledger; never fail the plan over it.
    Returns the status shown on the page."""
    from .db import store
    from .ledger import decisions, outcomes

    try:
        engine = store.ops_engine(DbConfig.from_env())
        missing = store.missing_tables(engine)
        if missing:
            return {"status": "waiting_on_dba", "missing": missing}
        out = decisions.record(engine, run, snap, version=VERSION)
        out["outcomes"] = outcomes.record_outcomes(engine, run["po_history"], run["today"])
        return {"status": "ok", **out}
    except Exception as exc:  # noqa: BLE001 -- the plan still publishes
        click.echo(f"ledger: {exc}", err=True)
        return {"status": "error", "error": str(exc)[:300]}


def _sku_map():
    """The confirmed pipeline_sku_map from PK_Ops; {} when it can't be read."""
    from .db import store

    try:
        engine = store.ops_engine(DbConfig.from_env())
        if store.missing_tables(engine):
            return {}
        return store.get_setting(engine, "pipeline_sku_map", {})
    except Exception as exc:  # noqa: BLE001 -- plan without the pipeline map
        click.echo(f"sku map: {exc}", err=True)
        return {}


def _replacements():
    """The part_replacements rules from PK_Ops; {} when they can't be read."""
    from .db import store

    try:
        engine = store.ops_engine(DbConfig.from_env())
        if store.missing_tables(engine):
            return {}
        return store.get_setting(engine, "part_replacements", {})
    except Exception as exc:  # noqa: BLE001 -- plan as MAX has it
        click.echo(f"replacements: {exc}", err=True)
        return {}


def _plan_once(erp):
    from . import snapshot
    from .run import build_plan

    run = build_plan(erp, sku_map=_sku_map(), replacements=_replacements())
    snap = snapshot.build(run, run["so_lines"])
    snap["ledger"] = _ledger(run, snap)
    snapshot.write(snap)
    snapshot.write_atp(snapshot.build_atp(run))
    _reconcile_done(snap)
    return snap


def _reconcile_done(snap):
    """Check every Done against this plan: confirmed if MAX covers the buy
    now, flagged if it still needs placing. Skips quietly without PK_Ops."""
    from .core import buy_status
    from .db import store

    try:
        engine = store.ops_engine(DbConfig.from_env())
        if store.missing_tables(engine):
            return
        status = store.get_setting(engine, "buy_status", {})
        log = store.get_setting(engine, "buy_log", [])
        parts = {b["part"] for b in snap["buys"] + snap.get("needs_source", [])}
        status, log, changed = buy_status.reconcile(status, log, parts, snap["generated_at"])
        if changed:
            store.put_setting(engine, "buy_status", status, "pk-mrp plan")
            store.put_setting(engine, "buy_log", log, "pk-mrp plan")
    except Exception as exc:  # noqa: BLE001 -- the plan is written; this can wait an hour
        click.echo(f"done check: {exc}", err=True)


@main.command("run")
def run_cmd():
    """Plan against live MAX, record it in the ledger, write the snapshot."""
    from . import snapshot

    snap = _plan_once(_erp())
    h = snap["headline"]
    click.echo(
        f"{snap['today']}: {h['buy_now']} buys to place ({h['late']} late), "
        f"{h['orders_waiting']} orders waiting, written to {snapshot.DATA_DIR}"
    )


@main.command()
@click.option("--every", default=60, help="Minutes between runs.")
def loop(every):
    """Plan now and then every N minutes, forever (the container's planner).

    A failed run is logged and retried next time; the last good snapshot
    stays on the page, with its time shown, rather than an empty one.
    """
    import time
    import traceback

    erp = None
    while True:
        started = time.time()
        try:
            erp = erp or _erp()
            snap = _plan_once(erp)
            h = snap["headline"]
            click.echo(
                f"planned {snap['generated_at']}: {h['buy_now']} buys, "
                f"ledger {snap['ledger'].get('status')} "
                f"(+{snap['ledger'].get('new', 0)} / -{snap['ledger'].get('closed', 0)}), "
                f"{time.time() - started:.1f}s",
                err=True,
            )
        except Exception:  # noqa: BLE001 -- keep the loop alive
            traceback.print_exc()
            if erp is not None:
                erp.close()
            erp = None
        time.sleep(max(60, every * 60 - (time.time() - started)))


@main.command()
@click.option("--port", default=8000)
def web(port):
    """Serve the web app (development server)."""
    from .web.app import create_app

    create_app().run(host="0.0.0.0", port=port)


@main.command()
def schema():
    """Print the PK_Ops DDL for the DBA (generated from db/store.py)."""
    from .db.store import ddl

    for stmt in ddl("mssql"):
        click.echo(stmt + "\n")


@main.command()
def check():
    """Connect to MAX and confirm the read-only path works."""
    df = _erp().query("SELECT COUNT(*) AS parts FROM Part_Master")
    click.echo(f"ExactMAX reachable, {int(df.iloc[0, 0]):,} parts.")
