"""core/analytics.py and the Analytics page."""

import json
from datetime import date, datetime

import pandas as pd
from test_rank_web import client  # noqa: F401 -- the snapshot-backed app fixture

from pkmrp.core.analytics import breakdown, impact, vendor_delivery

TODAY = date(2026, 10, 29)


def test_vendor_delivery_on_time_against_the_first_date_asked():
    ts = pd.Timestamp
    po = pd.DataFrame(
        [
            # vendor, part, created, org_due, first_receipt
            ("V1", "A", ts("2026-06-01"), ts("2026-06-15"), ts("2026-06-12")),  # early
            ("V1", "A", ts("2026-07-01"), ts("2026-07-15"), ts("2026-07-25")),  # 10 days late
            ("V1", "A", ts("2026-08-03"), ts("2026-08-14"), pd.NaT),  # not received
            ("V2", "B", ts("2026-09-01"), ts("2026-09-10"), ts("2026-09-10")),
            ("", "B", ts("2026-09-01"), ts("2026-09-10"), ts("2026-09-10")),  # no vendor
        ],
        columns=["vendor_id", "part", "created", "org_due", "first_receipt"],
    )
    out = vendor_delivery(po, {"A": 20}, {"V1": "ACME MACHINE"}, TODAY)
    v1 = next(v for v in out["vendors"] if v["vendor"] == "ACME MACHINE")
    assert v1["lines"] == 2 and v1["on_time_pct"] == 50.0 and v1["median_days_late"] == 10.0
    assert (
        v1["max_lead_wd"] == 20.0 and v1["real_lead_wd"] == 13.5
    )  # median of 9 and 18 working days
    assert [q["quarter"] for q in out["quarters"]] == ["2026 Q2", "2026 Q3"]
    json.dumps(out)  # plain floats, not numpy


def test_breakdown_buckets_and_rolls_up():
    buys = [
        {
            "buyer": "JM",
            "vendor": "X",
            "days_late": 0,
            "spend": 10,
            "sales_orders": ["1"],
            "for_parts": ["SYS"],
            "order_value": 100,
        },
        {
            "buyer": "JM",
            "vendor": "X",
            "days_late": 40,
            "spend": 5,
            "sales_orders": ["1", "2"],
            "for_parts": ["SYS", "KIT"],
            "order_value": 300,
        },
    ]
    bd = breakdown(buys, {"1": 100.0, "2": 200.0})
    assert bd["by_buyer"] == [{"name": "JM", "buys": 2, "late": 1, "spend": 15, "orders": 2}]
    assert {r["name"]: r["buys"] for r in bd["lateness"]}["31–90 days"] == 1
    assert bd["products"][0] == {"name": "SYS", "buys": 2, "value": 300.0}  # orders once each
    pegged = [
        dict(buys[1], pegs=[{"ref": "SO 1/01", "root": "SYS"}, {"ref": "SO 2/01", "root": "KIT"}])
    ]
    by = {r["name"]: r["value"] for r in breakdown(pegged, {"1": 100.0, "2": 200.0})["products"]}
    assert by == {"SYS": 100.0, "KIT": 200.0}  # each order to its own product


def test_impact_counts_a_part_once_and_says_matched_not_caused():
    t = datetime(2026, 10, 20, 7)
    recs = [
        # part A asked twice (qty changed): one piece of advice, placed in time
        dict(
            rec_id=1,
            kind="buy",
            part="A",
            qty=5,
            place_by=date(2026, 10, 24),
            created_at=t,
            sales_orders=["S1", "S2"],
            order_values={"S1": 200.0, "S2": 300.0},
            closed_at=t,
        ),
        dict(
            rec_id=2,
            kind="buy",
            part="A",
            qty=6,
            place_by=date(2026, 10, 24),
            created_at=t,
            sales_orders=["S1", "S2"],
            order_values={"S1": 200.0, "S2": 300.0},
            closed_at=None,
        ),
        # part B past its order-by, no PO
        dict(
            rec_id=3,
            kind="buy",
            part="B",
            qty=1,
            place_by=date(2026, 10, 22),
            created_at=t,
            sales_orders=["S3", "S1"],
            order_values={"S3": 900.0},
            closed_at=None,
        ),
        dict(
            rec_id=4,
            kind="push_out",
            part="C",
            qty=10,
            place_by=None,
            created_at=t,
            ref="PO 70111262/01/01",
            closed_at=None,
        ),
    ]
    outs = [
        dict(rec_id=2, what="po_placed", event_date=date(2026, 10, 23), qty=6),
        dict(rec_id=4, what="po_pushed", event_date=date(2026, 10, 25), qty=10),
    ]
    imp = impact(recs, outs, {"C": 12.5}, TODAY)
    assert imp["buys"] == 2 and imp["placed_on_time"] == 1 and imp["orders_protected"] == 2
    assert imp["order_value_protected"] == 500.0
    assert imp["not_placed_overdue"] == 1 and imp["orders_at_risk"] == 2
    assert imp["order_value_at_risk"] == 1100.0  # S1 counted once, valued from part A's why
    assert imp["pushed_usd"] == 125.0 and imp["median_days_to_po"] == 3


def test_analytics_page_renders_without_a_ledger(client):  # noqa: F811
    from sqlalchemy import create_engine
    from sqlalchemy.pool import StaticPool

    from pkmrp import snapshot
    from pkmrp.db import store
    from pkmrp.web.app import create_app

    snap = snapshot.load_latest()
    snap["analytics"] = {
        "vendor_delivery": {
            "vendors": [
                {
                    "vendor": "ACME",
                    "lines": 3,
                    "on_time_pct": 66.7,
                    "late_lines": 1,
                    "median_days_late": 4.0,
                    "real_lead_wd": 12.0,
                    "max_lead_wd": 30.0,
                }
            ],
            "quarters": [
                {"quarter": "2026 Q2", "lines": 3, "on_time_pct": 70.0},
                {"quarter": "2026 Q3", "lines": 4, "on_time_pct": 75.0},
            ],
        },
        "breakdown": breakdown(snap["buys"]),
    }
    snapshot.write(snap)  # also starts trend.json from history
    assert "2026-10-28" in snapshot.load_trend()
    engine = create_engine("sqlite://", poolclass=StaticPool)
    store.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(
            store.run.insert().values(
                run_id=1,
                plan_date=date(2026, 10, 28),
                started_at=datetime(2026, 10, 28, 6),
                inputs_hash="x",
                status="ok",
            )
        )
        conn.execute(
            store.recommendation.insert().values(
                rec_id=1,
                run_id=1,
                created_at=datetime(2026, 10, 28, 6),
                kind="buy",
                part="46-0020-01G",
                qty=5,
                place_by=date(2026, 10, 20),
                mode="shadow",
                content_hash="h",
                why_json=json.dumps(
                    {"sales_orders": ["20047846"], "order_values": {"20047846": 412000.0}}
                ),
            )
        )
    app = create_app()
    app.config["OPS_ENGINE"] = engine
    page = app.test_client().get("/analytics").get_data(as_text=True)
    assert "Is it saving money and orders?" in page and "Acme" in page
    assert "<polyline" in page and "matched" in page
    assert "$412K" in page and "already late when first advised" in page
