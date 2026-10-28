"""The pkmrp command. Shadow mode only: it reads MAX and reports; it never
writes anywhere yet."""

from collections import Counter

import click

from .config import DbConfig
from .db.erp import ErpClient

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


@main.command("run")
def run_cmd():
    """Plan against live MAX and write the snapshot the web app reads."""
    from . import snapshot
    from .run import build_plan

    run = build_plan(_erp())
    snap = snapshot.build(run, run["so_lines"])
    snapshot.write(snap)
    h = snap["headline"]
    click.echo(
        f"{snap['today']}: {h['buy_now']} buys to place ({h['late']} late), "
        f"{h['orders_waiting']} orders waiting, written to {snapshot.DATA_DIR}"
    )


@main.command()
@click.option("--port", default=8000)
def web(port):
    """Serve the web app (development server)."""
    from .web.app import create_app

    create_app().run(host="0.0.0.0", port=port)


@main.command()
def check():
    """Connect to MAX and confirm the read-only path works."""
    df = _erp().query("SELECT COUNT(*) AS parts FROM Part_Master")
    click.echo(f"ExactMAX reachable, {int(df.iloc[0, 0]):,} parts.")
