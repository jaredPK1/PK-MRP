from datetime import date, timedelta

import pandas as pd

from pkmrp.core.vendor_price import build, yoy

TODAY = date(2026, 10, 30)


def _rec(rows):
    return pd.DataFrame(
        [
            {"date": pd.Timestamp(d), "po": po, "line": "01", "delivery": "01", "part": p,
             "vendor_id": v, "qty": q, "unit_price": pr, "std_cost": std, "invoice": "INV"}
            for d, po, p, v, q, pr, std in rows
        ],
        columns=["date", "po", "line", "delivery", "part", "vendor_id", "qty", "unit_price",
                 "std_cost", "invoice"],
    )


def _open(rows):
    return pd.DataFrame(
        [
            {"po": po, "line": "01", "delivery": "01", "part": p, "vendor_id": v,
             "created": pd.Timestamp(c), "cur_due": pd.Timestamp(c + timedelta(days=30)),
             "qty_due": q, "unit_price": pr, "std_cost": std}
            for po, p, v, c, q, pr, std in rows
        ],
        columns=["po", "line", "delivery", "part", "vendor_id", "created", "cur_due", "qty_due",
                 "unit_price", "std_cost"],
    )


def D(days):
    return TODAY - timedelta(days=days)


def test_yoy_ignores_volume_and_mix_only_price_moves_it():
    rows = [
        (D(500), "A", 100, 10.0), (D(100), "A", 10, 11.0),  # A +10%, bought far less
        (D(500), "B", 10, 50.0), (D(100), "B", 100, 50.0),  # B flat, bought far more
        (D(100), "NEW", 1000, 1.0),  # only this year: not compared
    ]
    change, extra, cover, n = yoy(rows, TODAY)
    assert n == 2
    assert abs(change - (11 * 100 + 50 * 10) / (10 * 100 + 50 * 10) + 1) < 1e-9
    assert extra > 0 and 0 < cover < 1


def test_yoy_drops_pack_slips():
    rows = [(D(500), "A", 10, 1.0), (D(100), "A", 10, 100.0), (D(500), "B", 1, 5.0), (D(100), "B", 1, 5.0)]
    change, _e, _c, n = yoy(rows, TODAY)
    assert n == 1 and change == 0


def test_price_up_over_std_cheaper_elsewhere_and_drill_down():
    rec = _rec([
        (D(400), "70100001", "35-0126-00G", "DATAPRO", 400, 29.30, 29.30),
        (D(30), "70110001", "35-0126-00G", "DATAPRO", 400, 36.00, 29.30),
        (D(200), "70105000", "62-2522-00G", "AMS", 50, 7.60, 7.6),
        (D(20), "70110824", "62-2522-00G", "DUYCK", 100, 35.16, 7.6),
    ])
    opn = _open([("70110956", "41-3294-00G", "OSI", D(5), 50, 920.0, 467.30)])
    vp = build(rec, opn, {"DATAPRO": "DATAPRO INTL", "DUYCK": "DUYCK", "AMS": "AMS", "OSI": "OSI"},
               {"35-0126-00G": "cable"}, {"DATAPRO": 90.0}, TODAY)
    kinds = {(a["kind"], a["part"]) for a in vp["alerts"]}
    assert ("price_up", "35-0126-00G") in kinds
    assert ("over_std", "41-3294-00G") in kinds
    assert ("cheaper_else", "62-2522-00G") in kinds
    impacts = [a["impact"] for a in vp["alerts"]]
    assert impacts == sorted(impacts, reverse=True)
    lines = vp["detail"]["DATAPRO|35-0126-00G"]
    assert lines[0]["po"] == "70110001" and lines[0]["flag"] == "up"
    row = vp["parts"]["DATAPRO"][0]
    assert row["base_price"] == 29.3 and row["last_price"] == 36.0
    assert next(v for v in vp["vendors"] if v["vendor_id"] == "DATAPRO")["on_time_pct"] == 90.0


def test_open_po_with_two_deliveries_is_one_alert():
    opn = _open([
        ("70110956", "41-3294-00G", "OSI", D(5), 50, 920.0, 467.30),
        ("70110956", "41-3294-00G", "OSI", D(5), 50, 920.0, 467.30),
    ])
    vp = build(_rec([]), opn, {}, {}, {}, TODAY)
    over = [a for a in vp["alerts"] if a["kind"] == "over_std"]
    assert len(over) == 1 and round(over[0]["impact"]) == round((920 - 467.3) * 100)


def test_vendor_drift_needs_real_spend():
    rows = []
    for i in range(30):
        rows.append((D(500), f"7010{i:04d}", f"P{i}", "SHOP", 100, 100.0, 100.0))
        rows.append((D(60), f"7011{i:04d}", f"P{i}", "SHOP", 100, 112.0, 100.0))
    vp = build(_rec(rows), _open([]), {"SHOP": "SHOP"}, {}, {}, TODAY)
    drift = [a for a in vp["alerts"] if a["kind"] == "vendor_drift"]
    assert len(drift) == 1 and abs(vp["vendors"][0]["change_12m"] - 12.0) < 0.01


def test_snapshot_summary_reads_the_build_output():
    from pkmrp.snapshot import _vendor_price_summary

    rec = _rec([
        (D(400), "70100001", "35-0126-00G", "DATAPRO", 400, 29.30, 29.30),
        (D(30), "70110001", "35-0126-00G", "DATAPRO", 400, 36.00, 29.30),
    ])
    s = _vendor_price_summary(build(rec, _open([]), {}, {}, {}, TODAY))
    assert s["status"] == "ok" and s["alerts"] == 1 and s["top"][0]["part"] == "35-0126-00G"


def test_open_po_at_dearer_vendor_flags_even_if_other_sold_later():
    # 62-2571-00G: Duyck open at $197.56 (Aug), Ingenieur received at $123.91 (Oct)
    rec = _rec([(D(3), "70110338", "62-2571-00G", "ING", 50, 123.91, 130.09)])
    opn = _open([("70110821", "62-2571-00G", "DUYCK", D(63), 250, 197.56, 130.09)])
    vp = build(rec, opn, {"ING": "INGENIEUR", "DUYCK": "DUYCK"}, {}, {}, TODAY)
    ce = [a for a in vp["alerts"] if a["kind"] == "cheaper_else"]
    assert len(ce) == 1 and ce[0]["vendor_id"] == "DUYCK" and ce[0]["po"] == "70110821"
    assert round(ce[0]["impact"]) == round((197.56 - 123.91) * 250)


def test_small_increases_stay_off_the_list():
    rec = _rec([
        (D(400), "70100001", "35-0126-00G", "DATAPRO", 100, 29.30, 29.30),
        (D(30), "70110001", "35-0126-00G", "DATAPRO", 100, 36.00, 29.30),  # $670 at stake
    ])
    assert build(rec, _open([]), {}, {}, {}, TODAY)["alerts"] == []
