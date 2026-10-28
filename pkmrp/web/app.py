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


def _nice_date(v):
    """'2026-12-09' -> 'Wed 9 Dec' (with the year when it isn't this year)."""
    if not v:
        return ""
    d = date.fromisoformat(v) if isinstance(v, str) else v
    return f"{d:%a} {d.day} {d:%b}" + (f" {d.year}" if d.year != date.today().year else "")


def _month_name(v):
    d = date.fromisoformat(v) if isinstance(v, str) else v
    return f"{d:%b}" + (f" {d.year}" if d.year != date.today().year else "")


def _lead_words(source):
    """'realized (3 lines)' -> 'from its last 3 orders'; 'PURLT_01' -> 'MAX's lead time'."""
    s = source or ""
    if s.startswith("realized"):
        n = "".join(ch for ch in s if ch.isdigit())
        return f"from its last {n} orders" if n else "from its order history"
    if s.startswith("PURLT"):
        return "MAX's lead time (no history to check it)"
    if s.startswith("MFGLT"):
        return "MAX's build time"
    return s


def create_app():
    app = Flask(__name__)
    app.jinja_env.filters["money"] = _money
    app.jinja_env.filters["qty"] = _qty
    app.jinja_env.filters["nice_date"] = _nice_date
    app.jinja_env.filters["month_name"] = _month_name
    app.jinja_env.filters["lead_words"] = _lead_words

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
        plans = {cp["part"]: cp for cp in snap.get("committed_plans", [])}
        rows = snap.get("segments", [])
        vendors = sorted({cp["vendor"] for cp in plans.values() if cp["vendor"]})
        return render_template(
            "committed.html",
            snap=snap,
            rows=rows,
            plans=plans,
            vendors=vendors,
            counts=snap.get("segment_counts", {}),
        )

    @app.get("/committed/plan/<path:part>")
    def committed_plan(part):
        snap = snapshot.load_latest() or abort(404)
        cp = next((c for c in snap.get("committed_plans", []) if c["part"] == part), None)
        return render_template("_committed_plan.html", cp=cp or abort(404))

    @app.get("/committed/forecast.csv")
    def forecast_csv():
        """The supplier forecast letter: 12 months, frozen / firm / indicative."""
        import csv
        import io

        from flask import Response

        snap = snapshot.load_latest() or abort(404)
        vendor = request.args.get("vendor", "")
        plans = [c for c in snap.get("committed_plans", []) if not vendor or c["vendor"] == vendor]
        if not plans:
            abort(404)
        months = [m["month"][:7] for m in plans[0]["schedule"]]
        tags = [m["horizon"] for m in plans[0]["schedule"]]
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(
            [
                "PK forecast",
                snap["today"],
                "frozen = months 1-3, firm = 4-6, "
                "indicative = 7-12. Quantities are PK's requirement by month.",
            ]
        )
        w.writerow(["vendor", "our part", "your part", "description", *months])
        w.writerow(["", "", "", "", *tags])
        for c in sorted(plans, key=lambda c: (c["vendor"], c["part"])):
            w.writerow(
                [
                    c["vendor"],
                    c["part"],
                    c["vendor_part"],
                    c["description"],
                    *[_qty(m["requirement"]) for m in c["schedule"]],
                ]
            )
        name = (vendor or "all-vendors").replace(" ", "-").replace("/", "-")[:40]
        return Response(
            buf.getvalue(),
            mimetype="text/csv",
            headers={
                "Content-Disposition": (
                    f"attachment; filename=pk-forecast-{name}-{snap['today']}.csv"
                )
            },
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

    @app.get("/api/parts")
    def api_parts():
        """Part search for pickers: number fragments or description words."""
        from ..core.search import find

        data = snapshot.load_atp()
        q = (request.args.get("q") or "").strip()
        if not data or len(q) < 2:
            return {"parts": []}
        lines = data["timelines"]
        catalogue = (
            (p, v[1], v[0], p in lines and (lines[p][0] > 0 or bool(lines[p][1])))
            for p, v in data["parts"].items()
        )
        out = []
        for p, desc, ptype, active in find(q, catalogue, limit=12):
            out.append(
                {
                    "part": p,
                    "description": desc,
                    "type": "make" if ptype == "A" else "buy",
                    "on_hand": lines.get(p, [0])[0],
                    "active": active,
                }
            )
        return {"parts": out}

    @app.get("/promise")
    def promise_page():
        from ..core import atp
        from ..core.netting import Part

        data = snapshot.load_atp()
        part = (request.args.get("part") or "").strip().upper()
        result, error = None, None
        try:
            qty = float(request.args.get("qty") or 1)
        except ValueError:
            qty, error = 1.0, "Quantity has to be a number."
        asked = request.args.get("date") or ""
        if part and data and not error and part not in data["parts"]:
            from ..core.search import find

            hits = find(part, ((p, v[1], v[0], False) for p, v in data["parts"].items()), 1)
            if hits:
                part = hits[0][0]
        if part and data and not error:
            if part not in data["parts"]:
                error = (
                    f"Nothing matches “{part}” — try part of the number "
                    "or a word from the description."
                )
            else:
                today = date.fromisoformat(data["today"])
                parts = {
                    p: Part(p, t, description=desc, mfg_lt=mfg, purchase_lt=pur)
                    for p, (t, desc, mfg, pur) in data["parts"].items()
                }
                lines = {
                    p: (start, [(date.fromisoformat(d) if d else None, q) for d, q in ev])
                    for p, (start, ev) in data["timelines"].items()
                }
                children = {p: [tuple(k) for k in kids] for p, kids in data["children"].items()}
                lead = data["lead"]

                def lead_of(p):
                    return lead.get(p) or (parts[p].purchase_lt if p in parts else 0)

                requested = date.fromisoformat(asked) if asked else None
                result = atp.promise(part, qty, requested, children, lines, parts, lead_of, today)
                result["description"] = parts[part].description
                result["binding_description"] = (
                    parts[result["binding"]].description if result["binding"] in parts else ""
                )
        return render_template(
            "promise.html",
            data=data,
            part=part,
            qty=qty,
            asked=asked,
            result=result,
            error=error,
            snap=snapshot.load_latest(),
        )

    @app.get("/why/<path:part>")
    def why(part):
        """The why trace for one buy -- an HTMX fragment."""
        snap = snapshot.load_latest() or abort(404)
        b = next((b for b in snap["buys"] if b["part"] == part), None) or abort(404)
        return render_template("_why.html", b=b, today_iso=date.today().isoformat())

    app.config["DATA_DIR"] = os.environ.get("DATA_DIR", snapshot.DATA_DIR)
    return app
