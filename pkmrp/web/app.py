"""PK-MRP web app. Reads the snapshot `pkmrp run` writes; never queries MAX."""

import os
from datetime import date, datetime

from flask import Flask, abort, render_template, request

from .. import snapshot
from . import voice


def _first_name(email):
    local = (email or "").split("@", 1)[0]
    return local.split(".")[0].capitalize() if local else "there"


def _money(v):
    v = float(v or 0)
    if v >= 1_000_000:
        return f"${v / 1_000_000:.1f}M"
    if v >= 10_000:
        return f"${v / 1_000:.0f}K"
    if v >= 1_000:
        return f"${v / 1_000:.1f}K"
    return f"${v:,.0f}"


def _when(place_by, today):
    """A friendly chip for a place-by date: (text, tone)."""
    d = date.fromisoformat(place_by) if isinstance(place_by, str) else place_by
    days = (d - today).days
    if days < -13:
        return f"{-days // 7} weeks late", "late"
    if days < -1:
        return f"{-days} days late", "late"
    if days == -1:
        return "1 day late", "late"
    if days == 0:
        return "Place today", "today"
    return f"By {d:%a %-d %b}", "soon"


def _qty(v):
    v = float(v or 0)
    return f"{v:,.0f}" if v == int(v) else f"{v:,.2f}"


def create_app():
    app = Flask(__name__)
    app.jinja_env.filters["money"] = _money
    app.jinja_env.filters["qty"] = _qty

    @app.context_processor
    def _ctx():
        return {"script_root": request.script_root, "version": "0.1.0"}

    @app.get("/health")
    def health():
        return {"ok": True, "snapshot": bool(snapshot.load_latest())}

    @app.get("/")
    def home():
        snap = snapshot.load_latest()
        now = datetime.now()
        today = date.today()
        if snap is None:
            return render_template("empty.html", now=now), 200
        prev = snapshot.load_previous(snap["today"])
        buys = snap["buys"]
        for b in buys:
            b["when"], b["tone"] = _when(b["place_by"], today)
        email = request.headers.get("X-Auth-Request-Email", "")
        name = _first_name(email)
        h = snap["headline"]
        progress = snapshot.progress(snap, prev)
        facts = {
            "orders": h["orders_waiting"],
            "buys": h["buy_now"],
            "cleared": (progress or {}).get("cleared"),
            "top_part": buys[0]["part"] if buys else None,
            "top_value": _money(buys[0]["order_value"])
            if buys and buys[0]["order_value"]
            else None,
        }
        return render_template(
            "home.html",
            snap=snap,
            top=buys[:10],
            more=max(len(buys) - 10, 0),
            h=h,
            progress=progress,
            name=name,
            voice=voice.speak(now, name, facts),
            now=now,
        )

    @app.get("/buys")
    def buys_page():
        snap = snapshot.load_latest() or abort(404)
        today = date.today()
        buyer = request.args.get("buyer", "")
        rows = [b for b in snap["buys"] if not buyer or b["buyer"] == buyer]
        for b in rows:
            b["when"], b["tone"] = _when(b["place_by"], today)
        buyers = sorted({b["buyer"] for b in snap["buys"] if b["buyer"]})
        return render_template("buys.html", snap=snap, rows=rows, buyers=buyers, buyer=buyer)

    @app.get("/committed")
    def committed_page():
        snap = snapshot.load_latest() or abort(404)
        rows = snap.get("segments", [])
        return render_template(
            "committed.html", snap=snap, rows=rows, counts=snap.get("segment_counts", {})
        )

    @app.get("/lead-times")
    def params_page():
        snap = snapshot.load_latest() or abort(404)
        rows = snap.get("params", [])
        direction = request.args.get("direction", "")
        if direction in ("longer", "shorter"):
            rows = [r for r in rows if r["direction"] == direction]
        return render_template(
            "params.html",
            snap=snap,
            rows=rows,
            direction=direction,
            all_rows=snap.get("params", []),
        )

    @app.get("/lead-times.csv")
    def params_csv():
        import csv
        import io

        from flask import Response

        from ..core.params import CSV_COLUMNS

        snap = snapshot.load_latest() or abort(404)
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(snap.get("params", []))
        return Response(
            buf.getvalue(),
            mimetype="text/csv",
            headers={
                "Content-Disposition": f"attachment; filename=pk-mrp-lead-times-{snap['today']}.csv"
            },
        )

    @app.get("/why/<path:part>")
    def why(part):
        """The why trace for one buy -- an HTMX fragment."""
        snap = snapshot.load_latest() or abort(404)
        b = next((b for b in snap["buys"] if b["part"] == part), None) or abort(404)
        return render_template("_why.html", b=b)

    app.config["DATA_DIR"] = os.environ.get("DATA_DIR", snapshot.DATA_DIR)
    return app
