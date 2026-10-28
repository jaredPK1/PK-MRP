"""PK-MRP web app. Reads the snapshot `pkmrp run` writes; never queries MAX."""

import os
import random
from datetime import date, datetime

from flask import Flask, abort, render_template, request

from .. import snapshot

# One of these under the greeting -- the app should be pleasant to open.
NUDGES = (
    "Coffee first. Then these.",
    "The backlog is the plan. Here's the plan.",
    "Ten parts between the backlog and the dock.",
    "Short list, big orders behind it.",
    "Buy these and the kitting bench stays quiet.",
    "Every one of these is somebody's shipment.",
)


def _first_name(email):
    local = (email or "").split("@", 1)[0]
    return local.split(".")[0].capitalize() if local else "there"


def _greeting(now):
    h = now.hour
    return "Good morning" if h < 12 else "Good afternoon" if h < 17 else "Good evening"


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
        return render_template(
            "home.html",
            snap=snap,
            top=buys[:10],
            more=max(len(buys) - 10, 0),
            h=snap["headline"],
            progress=snapshot.progress(snap, prev),
            name=_first_name(email),
            greeting=_greeting(now),
            nudge=random.Random(snap["today"]).choice(NUDGES),
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

    @app.get("/why/<path:part>")
    def why(part):
        """The why trace for one buy -- an HTMX fragment."""
        snap = snapshot.load_latest() or abort(404)
        b = next((b for b in snap["buys"] if b["part"] == part), None) or abort(404)
        return render_template("_why.html", b=b)

    app.config["DATA_DIR"] = os.environ.get("DATA_DIR", snapshot.DATA_DIR)
    return app
