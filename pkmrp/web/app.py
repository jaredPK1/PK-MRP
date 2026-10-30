"""PK-MRP web app. Reads the snapshot `pkmrp run` writes; never queries MAX.
The one thing it writes is PK-MRP's own settings in PK_Ops: the Pipeline
page's confirmed SKU -> part map (editing role), and overbuys people cleared
with a reason and notes on parts (anyone signed in)."""

import json
import os
import re
from urllib.parse import quote
from datetime import date, datetime

from flask import Flask, abort, g, redirect, render_template, request, url_for

from .. import snapshot
from . import voice
from .whats_new import WHATS_NEW


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


def _nice_date(v, weekday=True):
    """'2026-12-09' -> 'Wed 9 Dec' (with the year when it isn't this year);
    weekday=False -> '9 Dec', for tight tables."""
    if not v:
        return ""
    d = date.fromisoformat(v) if isinstance(v, str) else v
    # non-breaking spaces: a date never splits across lines in a table
    out = (f"{d:%a} " if weekday else "") + f"{d.day} {d:%b}"
    out += f" {d.year}" if d.year != date.today().year else ""
    return out.replace(" ", "\u00a0")


def _month_name(v):
    d = date.fromisoformat(v) if isinstance(v, str) else v
    return f"{d:%b}" + (f" {d.year}" if d.year != date.today().year else "")


def _wdays(v):
    """Working days with weeks alongside: 261 -> '261 working days (~52 wks)'."""
    v = float(v or 0)
    return f"{v:.0f} working days (~{max(v / 5, 1):.0f} wks)" if v else ""


def _lead_words(source):
    """'realized (3 lines)' -> 'from its last 3 orders'; 'PURLT_01' -> 'MAX's lead time'."""
    s = source or ""
    if s.startswith("realized"):
        m = re.match(r"realized \((\d+) lines?(?: since (\d{4}))?\)", s)
        if not m:
            return "from its order history"
        n, since = m.groups()
        return f"from its last {n} orders" + (f", back to {since}" if since else "")
    if s.startswith("PURLT"):
        return "MAX's lead time (fewer than 3 orders in 10 years to check it)"
    if s.startswith("MFGLT"):
        return "MAX's build time"
    return s


SKU_MAP_KEY = "pipeline_sku_map"
CLEARED_KEY = "overbuy_cleared"
NOTES_KEY = "part_notes"
REPLACE_KEY = "part_replacements"
STATUS_KEY = "buy_status"
LOG_KEY = "buy_log"
BUYERS_KEY = "buyer_names"
# Ron's ECN app, the source of truth for ECNs; /ecn/?pn=<part> opens the
# part's ECN history there.
ECN_APP_URL = os.environ.get("ECN_APP_URL", "/ecn/")
CELEBRATE_AT = 10  # overbuys one person clears in a day earns a celebration


def _pick(item, key, label=None):
    """(label, value) for a chart point: a trend item is (day, numbers); a
    row dict takes its label from `label`."""
    if isinstance(item, dict):
        return (item.get(label), item.get(key))
    day, row = item
    return (_nice_date(day), (row or {}).get(key))


def create_app():
    app = Flask(__name__)
    app.jinja_env.filters["money"] = _money
    app.jinja_env.filters["qty"] = _qty
    app.jinja_env.filters["nice_date"] = _nice_date
    app.jinja_env.filters["month_name"] = _month_name
    app.jinja_env.filters["lead_words"] = _lead_words
    app.jinja_env.filters["wdays"] = _wdays
    app.jinja_env.filters["pick"] = _pick
    app.jinja_env.filters["person"] = _first_name

    def part_notes():
        """{part: [note]} from PK_Ops, read once per request; {} if unreadable."""
        if "part_notes" not in g:
            from ..db import store

            try:
                g.part_notes, g.notes_error = store.get_setting(ops_engine(), NOTES_KEY, {}), None
            except Exception as exc:  # noqa: BLE001 -- pages work without notes
                g.part_notes, g.notes_error = {}, str(exc)[:200]
        return g.part_notes

    def buy_status():
        """(status, buyer names) from PK_Ops, once per request."""
        if "buy_status" not in g:
            from ..core.buy_status import DEFAULT_BUYERS
            from ..db import store

            try:
                engine = ops_engine()
                g.buy_status = store.get_setting(engine, STATUS_KEY, {})
                g.buyer_names = store.get_setting(engine, BUYERS_KEY, list(DEFAULT_BUYERS))
            except Exception:  # noqa: BLE001 -- cards still render
                g.buy_status, g.buyer_names = {}, list(DEFAULT_BUYERS)
        return g.buy_status, g.buyer_names

    def buy_view(part):
        from ..core.buy_status import card_state

        snap = snapshot.load_latest() or {}
        status, _ = buy_status()
        recent = (snap.get("recent_po_parts") or {}).get(part, [])
        return card_state(status.get(part), snap.get("generated_at", ""), recent)

    def replacements():
        """{old: {part, use_up, why, by, at}} from PK_Ops, once per request."""
        if "replacements" not in g:
            from ..db import store

            try:
                g.replacements = store.get_setting(ops_engine(), REPLACE_KEY, {})
            except Exception:  # noqa: BLE001 -- pages work without them
                g.replacements = {}
        return g.replacements

    def held():
        """{part: hold note} -- parts someone put on hold; they come off every
        buy list until the note is removed."""
        return {
            p: next(n for n in ns if n["tag"] == "hold")
            for p, ns in part_notes().items()
            if any(n["tag"] == "hold" for n in ns)
        }

    def without_held(snap):
        """The snapshot as buyers should see it: held parts off the buy lists,
        the needs-source list and the shelf carts."""
        hold = held()
        if not hold:
            return snap, []
        carts = []
        for c in snap.get("shelf_orders") or []:
            items = [it for it in c["items"] if it["part"] not in hold]
            if items:
                carts.append({**c, "items": items, "lines": len(items),
                              "spend": round(sum(it.get("spend", 0) for it in items), 2)})
        out = {
            **snap,
            # renumbered, so Today's top ten reads 1-10 with no gaps
            "buys": [
                {**b, "rank": i}
                for i, b in enumerate((b for b in snap["buys"] if b["part"] not in hold), 1)
            ],
            "needs_source": [b for b in snap.get("needs_source", []) if b["part"] not in hold],
            "shelf_orders": carts,
            "vendor_plan": {
                v: [ln for ln in lines if ln["part"] not in hold]
                for v, lines in (snap.get("vendor_plan") or {}).items()
            },
        }
        on_hold = [
            {**b, "hold": hold[b["part"]]}
            for b in snap["buys"] + snap.get("needs_source", [])
            if b["part"] in hold
        ]
        return out, on_hold

    @app.context_processor
    def _ctx():
        from ..core.notes import TAG_SHORT, TAG_WORDS, TAGS

        return {
            "script_root": request.script_root,
            "version": "0.1.0",
            "notes_for": lambda part: part_notes().get(part, []),
            "note_tags": TAGS,
            "note_words": TAG_WORDS,
            "note_short": TAG_SHORT,
            "can_note": lambda: signed_in() and not g.get("notes_error"),
            "here": request.script_root + request.full_path.rstrip("?"),
            "ecn_for": ecn_for,
            "replacement_for": lambda part: replacements().get(part),
            "buy_view": buy_view,
            "buyer_names": lambda: buy_status()[1],
            "can_replace": lambda: can_edit() and not g.get("notes_error"),
            "ecn_link": lambda part: f"{ECN_APP_URL}?pn={quote(part)}",
            "ecn_app": ECN_APP_URL,
        }

    def ecn_for(part):
        """{"open": [...], "obsolete": ecn|None} from the latest plan, or None."""
        snap = snapshot.load_latest() or {}
        return ((snap.get("ecn") or {}).get("parts") or {}).get(part)

    @app.before_request
    def _dev_lock():
        """On the test copy (.70), DEV_ALLOWED_EMAILS keeps everyone but the
        named people on production (PROD_URL)."""
        allowed = os.environ.get("DEV_ALLOWED_EMAILS", "").strip()
        if not allowed or request.endpoint in ("health", "static"):
            return None
        me = (request.headers.get("X-Auth-Request-Email") or "").strip().lower()
        if me in {e.strip().lower() for e in allowed.split(",") if e.strip()}:
            return None
        prod = os.environ.get("PROD_URL", "").rstrip("/")
        link = f'<p><a href="{prod}/">Open PK-MRP</a></p>' if prod else ""
        return (f"<!doctype html><title>PK-MRP test copy</title><body style='font-family:sans-serif;"
                f"padding:40px'><h1>This is the PK-MRP test copy.</h1><p>Use the live one instead.</p>"
                f"{link}</body>"), 403

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
        snap, on_hold = without_held(snap)
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
            vendor_n=vendor_n(snap),
            on_hold=on_hold,
        )

    @app.get("/buys")
    def buys_page():
        snap, on_hold = without_held(snapshot.load_latest() or abort(404))
        today = date.today()
        who = request.args.get("who", "")
        status, _ = buy_status()

        def owner(part):
            return (status.get(part) or {}).get("owner", "")

        rows = [
            b for b in snap["buys"]
            if not who or (who == "-" and not owner(b["part"])) or owner(b["part"]) == who
        ]
        for b in rows:
            b["when"], b["tone"] = _when(b["place_by"], today)
        return render_template(
            "buys.html",
            snap=snap,
            rows=rows,
            who=who,
            vendor_n=vendor_n(snap),
            on_hold=on_hold,
        )

    @app.get("/overbuys")
    def overbuys_page():
        snap = snapshot.load_latest() or abort(404)
        ob = snap.get("overbuys") or {
            "po": [],
            "stock": [],
            "by_buyer": [],
            "totals": {},
            "new_days": 30,
        }
        from ..core.overbuy import REASONS, apply_cleared, clear_key
        from ..db import store

        try:
            cleared, error = store.get_setting(ops_engine(), CLEARED_KEY, {}), None
        except Exception as exc:  # noqa: BLE001 -- page still shows the overbuys
            cleared, error = {}, str(exc)[:200]
        ob = apply_cleared(ob, cleared)
        who = request.headers.get("X-Auth-Request-Email", "") or "unknown"
        today = date.today().isoformat()
        mine_today = sum(
            1 for c in cleared.values() if c.get("by") == who and c.get("at", "")[:10] == today
        )
        only_new = request.args.get("new") == "1"
        rows = [r for r in ob.get("po", []) if r["new"] or not only_new]
        return render_template(
            "overbuys.html",
            snap=snap,
            ob=ob,
            rows=rows,
            only_new=only_new,
            reasons=REASONS,
            reason_words={k: dict(v) for k, v in REASONS.items()},
            key_of=clear_key,
            clearable=signed_in() and error is None,
            error=error,
            saved=request.args.get("saved"),
            mine_today=mine_today,
            celebrate_at=CELEBRATE_AT,
        )

    @app.post("/overbuys/clear")
    def overbuys_clear():
        from ..core.overbuy import REASONS, clear_key
        from ..db import store

        if not signed_in():
            abort(403)
        key = request.form.get("key") or ""
        action = request.form.get("action")
        if action not in ("clear", "undo") or not key:
            abort(400)
        engine = ops_engine()
        current = store.get_setting(engine, CLEARED_KEY, {})
        who = request.headers.get("X-Auth-Request-Email", "") or "unknown"
        if action == "undo":
            current.pop(key, None)
        else:
            snap = snapshot.load_latest() or abort(404)
            ob = snap.get("overbuys") or {}
            row = next(
                (r for r in (ob.get("po") or []) + (ob.get("stock") or []) if clear_key(r) == key),
                None,
            )
            if row is None:
                abort(400, "That overbuy isn't on the current plan.")
            kind = "po" if "ref" in row else "stock"
            reason = request.form.get("reason") or ""
            note = (request.form.get("note") or "").strip()[:300]
            if reason not in dict(REASONS[kind]):
                abort(400, "Pick a reason.")
            if reason == "other" and not note:
                abort(400, "Say why in the note when the reason is Other.")
            current[key] = {
                "reason": reason,
                "note": note,
                "qty": row["qty"] if kind == "po" else row["extra"],
                "value": row["value"],
                "by": who,
                "at": datetime.now().isoformat(timespec="minutes"),
            }
        store.put_setting(engine, CLEARED_KEY, current, who)
        args = {"saved": action}
        if request.form.get("new") == "1":
            args["new"] = "1"
        return redirect(url_for("overbuys_page", **args) + "#saved")

    @app.get("/training")
    def training_page():
        snap = snapshot.load_latest()
        example = (snap or {}).get("buys", [None])[0] if snap and snap.get("buys") else None
        if example:
            example["when"], example["tone"] = _when(example["place_by"], date.today())
        return render_template("training.html", snap=snap, example=example, whats_new=WHATS_NEW)

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
                    for p, (t, desc, mfg, pur, *_) in data["parts"].items()
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
        rows = snap["buys"] + snap.get("needs_source", [])
        b = next((b for b in rows if b["part"] == part), None) or abort(404)
        return render_template("_why.html", b=b, today_iso=date.today().isoformat())

    def vendor_counts(snap, today, soon):
        """[(vendor, lines due now or late, lines in 4 weeks, $ in 4 weeks)]."""
        from ..core.calendar import plus_workdays
        from ..core.vendor_order import window

        four = plus_workdays(today, 20)
        out = []
        for v, lines in (snap.get("vendor_plan") or {}).items():
            rows = window(lines, today, four, soon)
            due = sum(1 for r in rows if r["status"] != "upcoming")
            out.append((v, due, len(rows), round(sum(r["spend"] for r in rows), 2)))
        return out

    def vendor_n(snap):
        """{vendor: parts to order from them in 4 weeks} for "+n more" links."""
        from ..core.calendar import plus_workdays

        today = date.fromisoformat(snap["today"])
        return {v: n for v, _due, n, _s in vendor_counts(snap, today, plus_workdays(today, 5))}

    def ledger_impact(today, so_values):
        """(impact dict, error text) from the Decision Ledger in PK_Ops."""
        from sqlalchemy import select

        from ..core.analytics import impact
        from ..db import store

        try:
            engine = ops_engine()
            r, o = store.recommendation, store.outcome
            with engine.connect() as conn:
                recs = [
                    dict(x._mapping)
                    for x in conn.execute(
                        select(
                            r.c.rec_id,
                            r.c.kind,
                            r.c.part,
                            r.c.ref,
                            r.c.qty,
                            r.c.place_by,
                            r.c.created_at,
                            r.c.closed_at,
                            r.c.why_json,
                        )
                    )
                ]
                outs = [
                    dict(x._mapping)
                    for x in conn.execute(select(o.c.rec_id, o.c.what, o.c.event_date, o.c.qty))
                ]
        except Exception as exc:  # noqa: BLE001 -- the rest of the page stands
            return None, str(exc)[:200]
        for x in recs:
            try:
                why = json.loads(x.pop("why_json") or "{}")
            except ValueError:
                why = {}
            x["sales_orders"] = why.get("sales_orders") or []
            x["order_values"] = why.get("order_values") or {}
        atp = snapshot.load_atp() or {}
        cost = {p: v[4] for p, v in (atp.get("parts") or {}).items() if len(v) > 4 and v[4]}
        return impact(recs, outs, cost, today, so_values), None

    @app.get("/analytics")
    def analytics_page():
        snap = snapshot.load_latest() or abort(404)
        today = date.fromisoformat(snap["today"])
        an = snap.get("analytics") or {}
        trend = sorted(snapshot.load_trend().items())
        imp, imp_error = ledger_impact(today, snap.get("so_values") or {})
        names = (snapshot.load_atp() or {}).get("parts") or {}
        bd = an.get("breakdown") or {}
        for r in bd.get("products") or []:
            desc = (names.get(r["name"]) or [None, ""])[1]
            if desc:
                r["name"] = f"{r['name']} · {desc.title()[:26]}"
        return render_template(
            "analytics.html",
            snap=snap,
            vd=an.get("vendor_delivery") or {},
            bd=bd,
            trend=trend,
            imp=imp,
            imp_error=imp_error,
            ob=(snap.get("overbuys") or {}).get("totals") or {},
            h=snap["headline"],
        )

    def weekly_html(base_url):
        """The end-of-week email, rendered with live data (also /weekly)."""
        from ..core import weekly
        from ..db import store

        # held parts are off the buy lists here too (same view as Today)
        snap, _ = without_held(snapshot.load_latest() or abort(404))
        today = date.fromisoformat(snap["today"])
        try:
            log = store.get_setting(ops_engine(), LOG_KEY, [])
        except Exception:  # noqa: BLE001 -- send without the Done section
            log = []
        imp, _ = ledger_impact(today, snap.get("so_values") or {})
        wk = weekly.build(snap, snapshot.load_trend(), log, imp, today)
        return render_template("email_weekly.html", wk=wk, base_url=base_url.rstrip("/")), wk

    app.config["WEEKLY_HTML"] = weekly_html

    @app.get("/weekly/email")
    def weekly_email():
        if not signed_in():
            abort(403)
        html, _ = weekly_html(request.url_root.rstrip("/") + request.script_root)
        return html

    @app.get("/weekly")
    def weekly_page():
        from ..cli import DEFAULT_RECIPIENTS, RECIPIENTS_KEY, WEEKLY_KEY
        from ..db import store

        if not signed_in():
            abort(403)
        try:
            engine = ops_engine()
            to = store.get_setting(engine, RECIPIENTS_KEY, DEFAULT_RECIPIENTS)
            last = store.get_setting(engine, WEEKLY_KEY, {})
        except Exception:  # noqa: BLE001
            to, last = DEFAULT_RECIPIENTS, {}
        return render_template(
            "weekly.html", snap=snapshot.load_latest(), to=to, last=last,
            editable=can_edit(), scheduler=os.environ.get("SCHEDULER_ENABLED", "0") == "1",
            me=request.headers.get("X-Auth-Request-Email", ""),
            sent=request.args.get("sent"), error=request.args.get("error"),
        )

    @app.post("/weekly/recipients")
    def weekly_recipients():
        from ..cli import RECIPIENTS_KEY
        from ..db import store

        if not can_edit():
            abort(403)
        emails = sorted({
            e.strip().lower() for e in re.split(r"[\s,;]+", request.form.get("emails", ""))
            if e.strip()
        })
        bad = [e for e in emails if not e.endswith(("@pkinetics.com", "@photonkinetics.com"))]
        if bad:
            abort(400, f"Only PK addresses: {', '.join(bad)}")
        who = request.headers.get("X-Auth-Request-Email", "") or "unknown"
        store.put_setting(ops_engine(), RECIPIENTS_KEY, emails, who)
        return redirect(url_for("weekly_page"))

    @app.post("/weekly/test")
    def weekly_test():
        from ..cli import send_weekly

        if not signed_in():
            abort(403)
        me = request.headers.get("X-Auth-Request-Email", "")
        if "@" not in me:
            abort(400, "Can't tell who you are to send you a test.")
        sent, err = send_weekly([me], record=False)
        return redirect(url_for("weekly_page", sent=",".join(sent), error=err or None))

    @app.get("/vendors")
    def vendors_page():
        from ..core.calendar import plus_workdays

        snap, _ = without_held(snapshot.load_latest() or abort(404))
        today = date.fromisoformat(snap["today"])
        rows = vendor_counts(snap, today, plus_workdays(today, 5))
        rows = [r for r in rows if r[2]]
        rows.sort(key=lambda r: (-r[1], -r[3], r[0]))
        return render_template("vendors.html", snap=snap, rows=rows)

    @app.get("/vendor")
    def vendor_page():
        from ..core.calendar import plus_workdays
        from ..core.vendor_order import window

        snap, _ = without_held(snapshot.load_latest() or abort(404))
        name = request.args.get("v", "")
        plan = snap.get("vendor_plan") or {}
        if name not in plan:
            abort(404)
        weeks = request.args.get("weeks", "4")
        weeks = int(weeks) if weeks in ("1", "2", "4", "8", "12") else 4
        today = date.fromisoformat(snap["today"])
        soon = plus_workdays(today, 5)
        lines = window(plan[name], today, plus_workdays(today, weeks * 5), soon)
        plans = {cp["part"]: cp for cp in snap.get("committed_plans", [])}
        for ln in lines:
            cp = plans.get(ln["part"])
            ln["release"] = cp["releases"][0] if cp and cp.get("releases") else None
        later = len(window(plan[name], today, plus_workdays(today, 60), soon)) - len(lines)
        return render_template(
            "vendor.html",
            snap=snap,
            vendor=name,
            lines=lines,
            weeks=weeks,
            later=later,
            pos=(snap.get("vendor_pos") or {}).get(name, []),
            focus=request.args.get("part", ""),
        )

    def ops_engine():
        """PK_Ops for settings; tests put a SQLite engine in OPS_ENGINE."""
        if app.config.get("OPS_ENGINE") is None:
            from ..config import DbConfig
            from ..db import store

            app.config["OPS_ENGINE"] = store.ops_engine(DbConfig.from_env())
        return app.config["OPS_ENGINE"]

    def can_edit():
        # pk_access sets pk_role; viewers read, admins and developers confirm.
        role = getattr(request, "pk_role", app.config.get("DEFAULT_ROLE"))
        return role in ("admin", "developer")

    def signed_in():
        # Anyone signed in to PK-MRP (buyers are viewers) may clear an overbuy
        # or note a part; neither changes a plan, and who did it is kept.
        return bool(getattr(request, "pk_role", app.config.get("DEFAULT_ROLE")))

    def sku_map():
        """(confirmed map, error text or None)."""
        from ..db import store

        try:
            return store.get_setting(ops_engine(), SKU_MAP_KEY, {}), None
        except Exception as exc:  # noqa: BLE001 -- page still shows proposals
            return {}, str(exc)[:200]

    @app.get("/pipeline")
    def pipeline_page():
        snap = snapshot.load_latest() or abort(404)
        pl = snap.get("pipeline") or {}
        confirmed, error = sku_map()
        proposals = pl.get("proposals") or {}
        todo = [u for u in pl.get("unmapped", []) if u["sku"] not in confirmed]
        for u in todo:
            u["proposal"] = proposals.get(u["sku"]) or {"confidence": "none", "candidates": []}
        rank = {"strong": 0, "likely": 1, "weak": 2, "none": 3}
        todo.sort(key=lambda u: (rank[u["proposal"]["confidence"]], -u["weighted_qty"]))
        done = sorted(confirmed.items(), key=lambda kv: kv[0].lower())
        return render_template(
            "pipeline.html",
            snap=snap,
            pl=pl,
            todo=todo,
            done=done,
            error=error,
            editable=can_edit() and error is None,
            saved=request.args.get("saved"),
        )

    @app.post("/pipeline/map")
    def pipeline_map():
        from ..db import store

        if not can_edit():
            abort(403)
        sku = (request.form.get("sku") or "").strip()
        action = request.form.get("action")
        if not sku or action not in ("use", "skip", "clear"):
            abort(400)
        engine = ops_engine()
        current = store.get_setting(engine, SKU_MAP_KEY, {})
        who = request.headers.get("X-Auth-Request-Email", "") or "unknown"
        stamp = {"by": who, "at": datetime.now().isoformat(timespec="minutes")}
        if action == "clear":
            current.pop(sku, None)
        elif action == "skip":
            current[sku] = {"skip": True, **stamp}
        else:
            part = (request.form.get("part") or "").strip().upper()
            atp = snapshot.load_atp()
            if not part or (atp and part not in atp["parts"]):
                abort(400, f"{part or 'No part'} isn't a make or buy part in MAX.")
            try:
                per = float(request.form.get("qty_per") or 1)
            except ValueError:
                abort(400)
            if per <= 0:
                abort(400)
            current[sku] = {"part": part, "qty_per": per, **stamp}
        store.put_setting(engine, SKU_MAP_KEY, current, who)
        return redirect(url_for("pipeline_page", saved=sku) + "#saved")

    @app.get("/notes")
    def notes_page():
        from ..core.notes import TAGS, listing

        snap = snapshot.load_latest()
        atp = snapshot.load_atp() or {}
        descriptions = {p: v[1] for p, v in (atp.get("parts") or {}).items()}
        tag = request.args.get("tag") or None
        notes = part_notes()
        moved = (snap or {}).get("replaced") or {}
        rules = sorted(
            ({"old": o, **r, "moved": moved.get(o)} for o, r in replacements().items()),
            key=lambda r: r["old"],
        )
        return render_template(
            "notes.html",
            snap=snap,
            rules=rules,
            descriptions=descriptions,
            replace=(request.args.get("replace") or "").strip().upper(),
            rows=listing(notes, descriptions, tag),
            counts={t: sum(1 for ns in notes.values() for n in ns if n["tag"] == t) for t, _ in TAGS},
            total=sum(len(ns) for ns in notes.values()),
            tag=tag,
            error=g.get("notes_error"),
            saved=request.args.get("saved"),
        )

    @app.post("/notes")
    def notes_save():
        from ..core import notes as pn
        from ..db import store

        if not signed_in():
            abort(403)
        part = (request.form.get("part") or "").strip().upper()
        action = request.form.get("action")
        back = request.form.get("next") or ""
        if not back.startswith("/") or back.startswith("//"):
            back = url_for("notes_page")
        if not part or action not in ("add", "remove"):
            abort(400)
        engine = ops_engine()
        current = store.get_setting(engine, NOTES_KEY, {})
        who = request.headers.get("X-Auth-Request-Email", "") or "unknown"
        if action == "remove":
            current = pn.remove(current, part, request.form.get("id") or "")
        else:
            atp = snapshot.load_atp()
            if atp and part not in atp["parts"]:
                abort(400, f"{part} isn't a part in MAX.")
            try:
                current = pn.add(
                    current,
                    part,
                    request.form.get("tag"),
                    request.form.get("text"),
                    who,
                    datetime.now().isoformat(timespec="minutes"),
                )
            except ValueError as exc:
                abort(400, str(exc))
        store.put_setting(engine, NOTES_KEY, current, who)
        sep = "&" if "?" in back else "?"
        return redirect(f"{back.split('#')[0]}{sep}noted={part}")

    @app.get("/check")
    def audit_page():
        snap = snapshot.load_latest() or abort(404)
        au = snap.get("audit") or {"counts": {}, "findings": [], "trend": []}
        groups = {}
        for f in au.get("findings", []):
            groups.setdefault(f["check"], []).append(f)
        return render_template("audit.html", snap=snap, au=au, groups=groups)

    @app.get("/fix-max")
    def fix_max_page():
        snap = snapshot.load_latest() or abort(404)
        fx = snap.get("fix_max") or {"status": "off"}
        return render_template("fix_max.html", snap=snap, fx=fx)

    @app.get("/fix-max.csv")
    def fix_max_csv():
        import csv
        import io

        from ..core.fix_max import bulk_rows

        snap = snapshot.load_latest() or abort(404)
        fx = snap.get("fix_max") or {}
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["record", "order", "line", "delivery", "current_part", "change_to",
                    "qty", "due", "customer_or_bill", "ecn"])
        w.writerows(bulk_rows(fx))
        name = f"fix-in-max-{snap['today']}.csv"
        return buf.getvalue(), 200, {
            "Content-Type": "text/csv; charset=utf-8",
            "Content-Disposition": f'attachment; filename="{name}"',
        }

    @app.post("/buy-status")
    def buy_status_save():
        from ..core import buy_status as bs
        from ..db import store

        if not signed_in():
            abort(403)
        part = (request.form.get("part") or "").strip().upper()
        action = request.form.get("action")
        back = request.form.get("next") or ""
        if not back.startswith("/") or back.startswith("//"):
            back = url_for("home")
        if not part or action not in ("owner", "done", "undo"):
            abort(400)
        engine = ops_engine()
        status = store.get_setting(engine, STATUS_KEY, {})
        who = request.headers.get("X-Auth-Request-Email", "") or "unknown"
        at = datetime.now().isoformat(timespec="seconds")
        if action == "owner":
            _, names = buy_status()
            owner = request.form.get("owner") or ""
            if owner and owner not in names:
                abort(400, "Pick a name from the list.")
            store.put_setting(engine, STATUS_KEY, bs.set_owner(status, part, owner, who, at), who)
        else:
            log = store.get_setting(engine, LOG_KEY, [])
            if action == "done":
                snap = snapshot.load_latest() or {}
                buy = next((b for b in snap.get("buys", []) + snap.get("needs_source", [])
                            if b["part"] == part), None)
                status, log = bs.mark_done(status, log, part, request.form.get("po"), who, at, buy)
            else:
                status, log = bs.undo_done(status, log, part, who, at)
            store.put_setting(engine, STATUS_KEY, status, who)
            store.put_setting(engine, LOG_KEY, log, who)
        return redirect(back)

    @app.get("/done")
    def done_page():
        from datetime import timedelta

        from ..db import store

        snap = snapshot.load_latest()
        try:
            log = store.get_setting(ops_engine(), LOG_KEY, [])
            error = None
        except Exception as exc:  # noqa: BLE001
            log, error = [], str(exc)[:200]
        period = request.args.get("period", "7")
        who = request.args.get("who", "")
        cutoff = None
        if period in ("1", "7", "30"):
            cutoff = (datetime.now() - timedelta(days=int(period) - 1)).date().isoformat()
        rows = [
            e for e in reversed(log)
            if (not cutoff or e["at"][:10] >= cutoff)
            and (not who or e.get("owner") == who or e["by"].split("@")[0].split(".")[0].lower() == who.lower())
        ]
        counts = {k: sum(1 for e in rows if e.get("check") == k)
                  for k in ("confirmed", "waiting", "no_po", "undone")}
        return render_template("done.html", snap=snap, rows=rows, counts=counts,
                               period=period, who=who, error=error)

    @app.post("/replacements")
    def replacements_save():
        from ..db import store

        if not can_edit():
            abort(403)
        old = (request.form.get("old") or "").strip().upper()
        action = request.form.get("action")
        if not old or action not in ("set", "remove"):
            abort(400)
        engine = ops_engine()
        current = store.get_setting(engine, REPLACE_KEY, {})
        who = request.headers.get("X-Auth-Request-Email", "") or "unknown"
        if action == "remove":
            current.pop(old, None)
        else:
            new = (request.form.get("new") or "").strip().upper()
            atp = snapshot.load_atp()
            for p in (old, new):
                if not p or (atp and p not in atp["parts"]):
                    abort(400, f"{p or 'No part'} isn't a make or buy part in MAX.")
            if new == old:
                abort(400, "A part can't replace itself.")
            current[old] = {
                "part": new,
                "use_up": request.form.get("use_up") == "1",
                "why": (request.form.get("why") or "").strip()[:300],
                "by": who,
                "at": datetime.now().isoformat(timespec="minutes"),
            }
        store.put_setting(engine, REPLACE_KEY, current, who)
        return redirect(url_for("notes_page", replaced=old) + "#replace")

    app.config["DATA_DIR"] = os.environ.get("DATA_DIR", snapshot.DATA_DIR)
    return app
