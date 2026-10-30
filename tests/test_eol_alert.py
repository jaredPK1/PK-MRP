from pkmrp.integrations import eol_alert, research

ITEM = {
    "part": "38-3001-00G",
    "description": "THERMO-ELECTRIC COOLER",
    "kind": "obsolete",
    "last_order": None,
    "replacements": [],
    "booked": 12.0,
    "on_hand": 60.0,
    "on_order": 0.0,
    "cover_months": 30.0,
    "ltb_qty": 0.0,
    "ltb_cost": 0.0,
    "systems": ["01-2302-03G"],
    "signals": [
        {
            "source": "distributor",
            "where": "digikey",
            "detail": "digikey: Obsolete",
            "link": "https://www.digikey.com/x",
        }
    ],
}


def test_only_obsolete_kinds_and_only_once():
    pcn = dict(ITEM, part="X", kind="pcn")
    assert eol_alert.new_items([ITEM, pcn], {}) == [ITEM]
    assert eol_alert.new_items([ITEM], {"38-3001-00G|obsolete": "2026-10-30"}) == []
    html = eol_alert.render([ITEM], "https://10.6.1.80/pk-mrp")
    assert "38-3001-00G" in html and "/pk-mrp/eol" in html and "covered by stock" in html


def test_alert_sends_on_production_and_remembers(tmp_path, monkeypatch):
    sent = []
    monkeypatch.setenv("SCHEDULER_ENABLED", "1")
    monkeypatch.setattr(
        eol_alert.notify, "fire", lambda *a, **k: sent.append((a, k)) or (list(a[2]), "")
    )
    state = {}
    out = research.alert_new([ITEM], state, str(tmp_path))
    assert out["sent"] == 1 and state["eol_alerted"] == {
        "38-3001-00G|obsolete": state["eol_alerted"]["38-3001-00G|obsolete"]
    }
    assert "patrick.tourreau@pkinetics.com" in sent[0][0][2]
    assert research.alert_new([ITEM], state, str(tmp_path))["sent"] == 0  # once only


def test_failed_send_is_retried_next_time(tmp_path, monkeypatch):
    monkeypatch.setenv("SCHEDULER_ENABLED", "1")
    monkeypatch.setattr(eol_alert.notify, "fire", lambda *a, **k: ([], "HTTP 500"))
    state = {}
    out = research.alert_new([ITEM], state, str(tmp_path))
    assert out["state"] == "error" and state["eol_alerted"] == {}


def test_off_away_from_production(tmp_path, monkeypatch):
    monkeypatch.setenv("SCHEDULER_ENABLED", "0")
    assert research.alert_new([ITEM], {}, str(tmp_path)) == {"state": "off"}
