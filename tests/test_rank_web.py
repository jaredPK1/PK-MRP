"""core/rank.py and the web pages, against a synthetic snapshot."""

import json
from datetime import date

import pytest

from pkmrp.core.netting import Part, Peg, PlannedOrder
from pkmrp.core.rank import buy_list

TODAY = date(2026, 10, 28)


def order(part, qty, place_by, need_by, refs):
    pegs = tuple(Peg("so", r, "SYS", ("SYS", part)) for r in refs)
    return PlannedOrder(part, "buy", qty, need_by, place_by, 20, "PURLT_01", pegs, place_by < TODAY)


def test_ranked_by_order_value_then_lateness_and_grouped_by_part():
    planned = [
        order("A", 2, date(2026, 10, 1), date(2026, 11, 1), ["SO 1/01"]),
        order("A", 3, date(2026, 10, 20), date(2026, 11, 20), ["SO 1/02"]),
        order("B", 1, date(2026, 10, 27), date(2026, 12, 1), ["SO 2/01"]),
        order("C", 1, date(2027, 2, 1), date(2027, 3, 1), ["SO 3/01"]),  # beyond horizon
    ]
    parts = {p: Part(p, "B", unit_cost=10.0) for p in "ABC"}
    out = buy_list(planned, parts, {}, {"1": 500.0, "2": 900.0}, {"1": "Acme", "2": "Zed"}, TODAY)
    assert [b["part"] for b in out] == ["B", "A"]
    a = out[1]
    assert a["qty"] == 5 and a["orders"] == 1 and a["order_value"] == 500.0
    assert a["days_late"] == 27 and a["spend"] == 50.0 and a["customers"] == ["Acme"]
    assert [b["rank"] for b in out] == [1, 2]


@pytest.fixture
def client(tmp_path, monkeypatch):
    from pkmrp import snapshot

    monkeypatch.setattr(snapshot, "DATA_DIR", str(tmp_path))
    snap = {
        "generated_at": "2026-10-28T06:00:00",
        "today": "2026-10-28",
        "mode": "shadow",
        "counts": {},
        "timings": {},
        "exceptions": {},
        "headline": {
            "buy_now": 1,
            "late": 1,
            "orders_waiting": 1,
            "order_value_waiting": 412000,
            "expedites": 3,
            "push_outs": 1,
            "cancel_candidates": 0,
            "beyond_backlog": 7,
            "unscheduled_lines": 652,
            "unplannable_lines": 78,
            "consigned_pairs": 115,
        },
        "buys": [
            {
                "rank": 1,
                "part": "46-0020-01G",
                "description": "LENS, 1X RELAY",
                "buyer": "RB",
                "qty": 25,
                "unit_cost": 900,
                "spend": 22500,
                "place_by": "2026-10-01",
                "need_by": "2026-12-01",
                "days_late": 27,
                "lead_days": 105,
                "lead_source": "PURLT_01",
                "vendor": "IDEX",
                "orders": 1,
                "order_value": 412000,
                "customers": ["Acme"],
                "for_parts": ["SYS"],
                "sales_orders": ["20048246"],
                "planned_lines": 1,
                "wo_only": False,
                "late_lines": 6,
                "story": {
                    "part": "46-0020-01G",
                    "description": "LENS, 1X RELAY",
                    "on_hand": 20,
                    "on_order": 0,
                    "total_need": 42,
                    "runs_out": "2026-12-09",
                    "covered_until": "2026-12-02",
                    "overdue_need": 8,
                    "buy_qty": 22,
                    "vendor": "REXNORD INDUSTRIES",
                    "lead_days": 79,
                    "lead_source": "realized (3 lines)",
                    "arrives_if_ordered_today": "2027-02-20",
                    "orders_slipping": 4,
                    "goes_into": [
                        {"part": "06-2025-00G", "description": "APERTURE WHEEL ASSY", "units": 19}
                    ],
                    "waiting": [
                        {
                            "kind": "order",
                            "ref": "SO 20048246",
                            "customer": "JIANGSU ETERN",
                            "units": 5,
                            "need_by": "2026-12-09",
                            "ships": "2027-01-15",
                            "value": 12200000,
                            "system": "00-0988-02G",
                            "system_description": "2304 MFD UNIT",
                            "slips": True,
                            "short_from": "2026-12-09",
                        }
                    ],
                    "waiting_more": 0,
                    "months": [{"month": "2026-12-01", "need": 22, "arriving": 0, "balance": -2}],
                },
                "pegs": [{"ref": "SO 20048246/05", "path": ["SYS", "46-0020-01G"], "value": 0}],
                "exceptions": [],
            }
        ],
    }
    snap["needs_source"] = [
        dict(
            snap["buys"][0],
            part="88-0719-00G",
            description="MAGNET, .250 DIA NEODYMIUM",
            vendor="",
            unit_cost=0.0,
            story=dict(snap["buys"][0]["story"], vendor=""),
        )
    ]
    snapshot.write(snap)
    prev = dict(
        snap,
        today="2026-10-27",
        buys=snap["buys"] + [dict(snap["buys"][0], part="53-4104-00G", order_value=90000)],
    )
    (tmp_path / "history" / "2026-10-27.json").write_text(json.dumps(prev))
    from pkmrp.web.app import create_app

    return create_app().test_client()


def test_home_greets_ranks_and_celebrates(client):
    html = client.get("/", headers={"X-Auth-Request-Email": "rob.smith@pkinetics.com"}).get_data(
        as_text=True
    )
    assert "Rob" in html and "46-0020-01G" in html and "Today's top 1" in html
    assert "came off the list since 10-27" in html and "✓ 1" in html
    assert "Shadow mode" in html


def test_why_fragment_and_full_list(client):
    why = client.get("/why/46-0020-01G").get_data(as_text=True)
    assert "Runs out" in why and "Rexnord Industries" in why and "Jiangsu Etern" in why
    assert "from its last 3 orders" in why and "4 orders need it before then" in why
    assert "Aperture wheel assy" in why and "slips" in why
    assert client.get("/why/NOPE").status_code == 404
    assert "46-0020-01G" in client.get("/buys").get_data(as_text=True)


def test_no_snapshot_is_a_friendly_page(tmp_path, monkeypatch):
    from pkmrp import snapshot
    from pkmrp.web.app import create_app

    monkeypatch.setattr(snapshot, "DATA_DIR", str(tmp_path / "none"))
    r = create_app().test_client().get("/")
    assert r.status_code == 200 and "Warming up" in r.get_data(as_text=True)


def test_voice_follows_the_clock_and_holds_within_the_hour():
    from datetime import datetime

    from pkmrp.web import voice

    wed = lambda h, m=0: datetime(2026, 10, 28, h, m)  # noqa: E731
    assert [voice.part_of_day(wed(h)) for h in (5, 9, 12, 15, 19, 23)] == [
        "early",
        "morning",
        "midday",
        "afternoon",
        "evening",
        "late",
    ]
    assert voice.part_of_day(datetime(2026, 10, 31, 10)) == "weekend"
    a, b = voice.speak(wed(9, 5), "Rob"), voice.speak(wed(9, 50), "Rob")
    assert a == b and "Rob" in a["greeting"]
    sat = voice.speak(datetime(2026, 10, 31, 10), "Rob")
    assert sat["part"] == "weekend"
    seen = {voice.speak(wed(h), "Rob")["line"] for h in range(6, 22)}
    assert len(seen) > 4  # it actually changes through the day


def test_voice_never_says_zero():
    from datetime import datetime

    from pkmrp.web import voice

    for h in range(24):
        out = voice.speak(datetime(2026, 10, 28, h), "Rob", {"orders": 0, "cleared": 0})
        assert "0 booked" not in out["line"] and "{" not in out["line"]


def test_overbuys_and_training_pages(client):
    html = client.get("/training").get_data(as_text=True)
    assert "How to use PK-MRP" in html and "46-0020-01G" in html and "What&#39;s new" not in html
    assert "Overbuys page" in html
    assert client.get("/overbuys").status_code == 200


def test_parts_with_no_source_get_their_own_list(client):
    html = client.get("/").get_data(as_text=True)
    assert "Needs a source" in html and "88-0719-00G" in html and "1 with no cost in MAX" in html
    why = client.get("/why/88-0719-00G").get_data(as_text=True)
    assert "Nobody has bought this before" in why and "no cost for it" in why


def _pipeline_client(tmp_path, monkeypatch, role):
    from sqlalchemy import create_engine
    from sqlalchemy.pool import StaticPool

    from pkmrp import snapshot
    from pkmrp.db import store
    from pkmrp.web.app import create_app

    monkeypatch.setattr(snapshot, "DATA_DIR", str(tmp_path))
    snap = json.loads((tmp_path / "latest.json").read_text())
    snap["pipeline"] = {
        "status": "ok",
        "unmapped": [
            {"sku": "FK11-SAE-U", "weighted_qty": 4.0, "bookings": 2, "description": ""},
            {"sku": "2304 Option", "weighted_qty": 9.0, "bookings": 5, "description": "MFD"},
        ],
        "proposals": {
            "FK11-SAE-U": {
                "confidence": "strong",
                "orders": 9,
                "catch_all": False,
                "candidates": [
                    {
                        "part": "01-0351-00G",
                        "description": "FK11-SAE-U CLEAVER",
                        "qty_per": 1.0,
                        "evidence": ["on 9 of 9 orders that had FK11-SAE-U"],
                    }
                ],
            },
            "2304 Option": {"confidence": "weak", "orders": 0, "catch_all": True, "candidates": []},
        },
        "undated": [
            {"booking": "BK-9", "customer": "Acme", "status": "open", "p_win": 50, "skus": ["X"]}
        ],
        "undated_bookings": 1,
    }
    snapshot.write(snap)
    snapshot.write_atp(
        {"parts": {"01-0351-00G": ["A", "FK11-SAE-U CLEAVER", 0, 0]}, "timelines": {}}
    )
    engine = create_engine("sqlite://", poolclass=StaticPool)
    store.metadata.create_all(engine)
    app = create_app()
    app.config.update(OPS_ENGINE=engine, DEFAULT_ROLE=role)
    return app.test_client(), engine


def test_pipeline_page_confirms_skips_and_undoes(client, tmp_path, monkeypatch):
    from pkmrp.db import store

    c, engine = _pipeline_client(tmp_path, monkeypatch, "admin")
    page = c.get("/pipeline").get_data(as_text=True)
    assert "01-0351-00G" in page and "catch-all" in page and "BK-9" in page
    assert page.index("FK11-SAE-U") < page.index("2304 Option")  # surest first
    r = c.post(
        "/pipeline/map",
        data={"sku": "FK11-SAE-U", "part": "01-0351-00G", "qty_per": "2", "action": "use"},
    )
    assert r.status_code == 302
    c.post("/pipeline/map", data={"sku": "2304 Option", "action": "skip"})
    saved = store.get_setting(engine, "pipeline_sku_map")
    assert saved["FK11-SAE-U"]["part"] == "01-0351-00G" and saved["FK11-SAE-U"]["qty_per"] == 2.0
    assert saved["2304 Option"]["skip"] is True
    assert "To check" not in c.get("/pipeline").get_data(as_text=True)
    c.post("/pipeline/map", data={"sku": "2304 Option", "action": "clear"})
    assert "2304 Option" not in store.get_setting(engine, "pipeline_sku_map")
    bad = c.post("/pipeline/map", data={"sku": "FK12", "part": "NOT-A-PART", "action": "use"})
    assert bad.status_code == 400


def test_pipeline_viewers_read_but_cannot_confirm(client, tmp_path, monkeypatch):
    c, _ = _pipeline_client(tmp_path, monkeypatch, "viewer")
    page = c.get("/pipeline").get_data(as_text=True)
    assert "01-0351-00G" in page and "Use this" not in page
    r = c.post("/pipeline/map", data={"sku": "FK11-SAE-U", "part": "01-0351-00G", "action": "use"})
    assert r.status_code == 403


def _overbuy_client(tmp_path, monkeypatch, role):
    from sqlalchemy import create_engine
    from sqlalchemy.pool import StaticPool

    from pkmrp import snapshot
    from pkmrp.db import store
    from pkmrp.web.app import create_app

    monkeypatch.setattr(snapshot, "DATA_DIR", str(tmp_path))
    snap = json.loads((tmp_path / "latest.json").read_text())
    snap["overbuys"] = {
        "po": [
            {"part": f"P{i}", "description": "SCREW", "ref": f"PO 7011{i:04d}/01/01",
             "what": "not needed", "kind": "cancel_candidate", "qty": 10, "value": 5.0,
             "buyer": "AS", "vendor": "MCMASTER", "placed": None, "due": None, "new": False,
             "days_early": None}
            for i in range(12)
        ],
        "stock": [{"part": "LENS", "description": "LENS", "buyer": "LB", "on_hand": 9,
                   "needed": 1, "extra": 8, "value": 800.0, "idle": False}],
        "by_buyer": [{"buyer": "AS", "po_value": 60.0, "po_lines": 12, "new_value": 0}],
        "totals": {"not_needed": 60.0, "stock_extra": 800.0, "new_lines": 0},
        "new_days": 30,
    }
    snapshot.write(snap)
    engine = create_engine("sqlite://", poolclass=StaticPool)
    store.metadata.create_all(engine)
    app = create_app()
    app.config.update(OPS_ENGINE=engine, DEFAULT_ROLE=role)
    return app.test_client(), engine


def test_overbuys_clear_with_a_reason_undo_and_celebrate_at_ten(client, tmp_path, monkeypatch):
    from pkmrp.db import store

    c, engine = _overbuy_client(tmp_path, monkeypatch, "viewer")  # buyers are viewers
    page = c.get("/overbuys").get_data(as_text=True)
    assert "Clear…" in page and "PO|P0|PO 70110000/01/01" in page
    assert c.post("/overbuys/clear", data={"key": "PO|P0|PO 70110000/01/01", "action": "clear"}).status_code == 400
    other = {"key": "STOCK|LENS", "action": "clear", "reason": "other"}
    assert c.post("/overbuys/clear", data=other).status_code == 400  # Other needs a note
    r = c.post("/overbuys/clear", data={**other, "note": "Kit stock at KJS"})
    assert r.status_code == 302
    saved = store.get_setting(engine, "overbuy_cleared")
    assert saved["STOCK|LENS"]["note"] == "Kit stock at KJS" and saved["STOCK|LENS"]["qty"] == 8
    page = c.get("/overbuys?saved=clear").get_data(as_text=True)
    assert 'id="cleared"' in page and "Kit stock at KJS" in page and 'id="celebrate"' not in page
    for i in range(9):
        c.post("/overbuys/clear", data={"key": f"PO|P{i}|PO 7011{i:04d}/01/01",
                                         "action": "clear", "reason": "spares"})
    page = c.get("/overbuys?saved=clear").get_data(as_text=True)
    assert 'id="celebrate"' in page and "cleared 10 today" in page
    c.post("/overbuys/clear", data={"key": "STOCK|LENS", "action": "undo"})
    assert "STOCK|LENS" not in store.get_setting(engine, "overbuy_cleared")
    bad = c.post("/overbuys/clear", data={"key": "PO|NOPE|PO 1/01/01", "action": "clear",
                                          "reason": "spares"})
    assert bad.status_code == 400


def test_overbuys_clearing_needs_sign_in(client, tmp_path, monkeypatch):
    c, _ = _overbuy_client(tmp_path, monkeypatch, None)
    assert "overbuys/clear" not in c.get("/overbuys").get_data(as_text=True)
    r = c.post("/overbuys/clear", data={"key": "STOCK|LENS", "action": "clear", "reason": "spares"})
    assert r.status_code == 403


def test_promise_page_reads_the_atp_file_as_written(client):
    from pkmrp import snapshot

    # parts rows carry unit cost as a fifth field (Analytics); the page must not care
    snapshot.write_atp(
        {
            "today": "2026-10-28",
            "parts": {"LENS": ["B", "LENS 50MM", 0.0, 20.0, 900.0]},
            "timelines": {"LENS": [2.0, []]},
            "children": {},
            "lead": {"LENS": 20.0},
        }
    )
    r = client.get("/promise?part=LENS&qty=1")
    assert r.status_code == 200 and "LENS" in r.get_data(as_text=True)
