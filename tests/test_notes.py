"""core/notes.py and the notes shown on every page."""

import json

import pytest

from pkmrp.core import notes as pn


def test_add_remove_and_list():
    n = pn.add({}, "LENS", "ecn", " ECN 4410 ", "a@pk", "2026-10-29T09:00")
    n = pn.add(n, "LENS", "other", "ask Rob", "b@pk", "2026-10-29T10:00")
    assert [x["tag"] for x in n["LENS"]] == ["ecn", "other"] and n["LENS"][0]["text"] == "ECN 4410"
    rows = pn.listing(n, {"LENS": "LENS 50MM"})
    assert rows[0]["text"] == "ask Rob" and rows[0]["description"] == "LENS 50MM"
    assert [r["tag"] for r in pn.listing(n, {}, "ecn")] == ["ecn"]
    n = pn.remove(n, "LENS", n["LENS"][0]["id"])
    n = pn.remove(n, "LENS", n["LENS"][0]["id"])
    assert n == {}
    with pytest.raises(ValueError):
        pn.add({}, "LENS", "other", "  ", "a", "t")  # Other needs words
    with pytest.raises(ValueError):
        pn.add({}, "LENS", "nonsense", "x", "a", "t")


@pytest.fixture
def noted(tmp_path, monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.pool import StaticPool

    from pkmrp import snapshot
    from pkmrp.db import store
    from pkmrp.web.app import create_app

    monkeypatch.setattr(snapshot, "DATA_DIR", str(tmp_path))
    snapshot.write(
        {
            "generated_at": "2026-10-29T06:00:00",
            "today": "2026-10-29",
            "headline": {},
            "counts": {},
            "buys": [],
            "overbuys": {
                "po": [
                    {"part": "LENS", "description": "LENS 50MM", "ref": "PO 1/01/01",
                     "what": "not needed", "kind": "cancel_candidate", "qty": 1, "value": 900.0,
                     "buyer": "LB", "vendor": "IDEX", "placed": None, "due": None, "new": False,
                     "days_early": None}
                ],
                "stock": [],
                "by_buyer": [],
                "totals": {},
                "new_days": 30,
            },
        }
    )
    snapshot.write_atp({"today": "2026-10-29", "parts": {"LENS": ["B", "LENS 50MM", 0, 20, 900]},
                        "timelines": {}, "children": {}, "lead": {}})
    engine = create_engine("sqlite://", poolclass=StaticPool)
    store.metadata.create_all(engine)
    app = create_app()
    app.config.update(OPS_ENGINE=engine, DEFAULT_ROLE="viewer")
    return app.test_client(), engine


def test_a_note_saves_on_the_part_and_shows_wherever_it_appears(noted):
    from pkmrp.db import store

    c, engine = noted
    page = c.get("/overbuys").get_data(as_text=True)
    assert "+ note" in page
    r = c.post("/notes", data={"part": "lens", "tag": "ecn", "text": "ECN 4410",
                               "action": "add", "next": "/overbuys?new=1"})
    assert r.status_code == 302 and r.headers["Location"].endswith("/overbuys?new=1&noted=LENS")
    saved = store.get_setting(engine, "part_notes")
    assert saved["LENS"][0]["tag"] == "ecn"
    assert "ECN coming" in c.get("/overbuys").get_data(as_text=True)
    page = c.get("/notes").get_data(as_text=True)
    assert "ECN 4410" in page and "ECN being created · 1" in page
    nid = saved["LENS"][0]["id"]
    c.post("/notes", data={"part": "LENS", "id": nid, "action": "remove", "next": "/notes"})
    assert store.get_setting(engine, "part_notes") == {}


def test_notes_refuse_bad_input_and_offsite_redirects(noted):
    c, _ = noted
    bad = {"part": "NOPE", "tag": "ecn", "action": "add"}
    assert c.post("/notes", data=bad).status_code == 400
    assert c.post("/notes", data={"part": "LENS", "tag": "other", "action": "add"}).status_code == 400
    r = c.post("/notes", data={"part": "LENS", "tag": "obsolete", "action": "add",
                               "next": "//evil.example/x"})
    assert r.status_code == 302 and "evil" not in r.headers["Location"]


def test_notes_need_sign_in(noted):
    c, _ = noted
    c.application.config["DEFAULT_ROLE"] = None
    assert "+ note" not in c.get("/overbuys").get_data(as_text=True)
    assert c.post("/notes", data={"part": "LENS", "tag": "ecn", "action": "add"}).status_code == 403
