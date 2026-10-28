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
                "ledger": [{"date": None, "qty": 0, "kind": "on_hand", "ref": "x"}],
                "pegs": [{"ref": "SO 20048246/05", "path": ["SYS", "46-0020-01G"], "value": 0}],
                "exceptions": [],
            }
        ],
    }
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
    assert "Rob." in html and "46-0020-01G" in html and "Today's top 1" in html
    assert "came off the list since 10-27" in html and "✓ 1" in html
    assert "Shadow mode" in html


def test_why_fragment_and_full_list(client):
    why = client.get("/why/46-0020-01G").get_data(as_text=True)
    assert "SO 20048246/05" in why and "ordering by" in why
    assert client.get("/why/NOPE").status_code == 404
    assert "46-0020-01G" in client.get("/buys").get_data(as_text=True)


def test_no_snapshot_is_a_friendly_page(tmp_path, monkeypatch):
    from pkmrp import snapshot
    from pkmrp.web.app import create_app

    monkeypatch.setattr(snapshot, "DATA_DIR", str(tmp_path / "none"))
    r = create_app().test_client().get("/")
    assert r.status_code == 200 and "Warming up" in r.get_data(as_text=True)
