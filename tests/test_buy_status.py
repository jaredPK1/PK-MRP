"""core/buy_status.py: who's on a buy, and Done checked against MAX."""

from pkmrp.core import buy_status as bs


def test_owner_done_reconcile_confirm_and_flag():
    st = bs.set_owner({}, "LENS", "Aaron", "a@pk", "2026-10-29T09:00:00")
    st = bs.set_owner(st, "MOTOR", "Rob", "r@pk", "2026-10-29T09:00:00")
    st, log = bs.mark_done(st, [], "LENS", " 70111309 ", "a@pk", "2026-10-29T10:00:00",
                           {"description": "LENS 50MM", "qty": 4, "vendor": "IDEX"})
    st, log = bs.mark_done(st, log, "MOTOR", "", "r@pk", "2026-10-29T10:05:00")
    assert log[0]["po"] == "70111309" and log[0]["owner"] == "Aaron" and log[0]["check"] == "waiting"
    # a plan made before the Done changes nothing
    same, log2, changed = bs.reconcile(st, log, {"LENS", "MOTOR"}, "2026-10-29T09:30:00")
    assert not changed and same == st
    # next plan: LENS covered by MAX (gone), MOTOR still a buy
    st2, log2, changed = bs.reconcile(st, log, {"MOTOR"}, "2026-10-29T11:00:00")
    assert changed and "LENS" not in st2  # done confirmed, owner cleared
    assert st2["MOTOR"]["done"]["check"] == "no_po" and st2["MOTOR"]["owner"] == "Rob"
    assert [e["check"] for e in log2] == ["confirmed", "no_po"]
    v = bs.card_state(st2["MOTOR"], "2026-10-29T11:00:00", [])
    assert v["done"]["state"] == "no_po"
    # undo logs it and frees the card
    st3, log3 = bs.undo_done(st2, log2, "MOTOR", "r@pk", "2026-10-29T11:10:00")
    assert "done" not in st3["MOTOR"] and log3[1]["check"] == "undone"


def test_card_waits_until_a_plan_after_the_done_and_finds_the_po():
    st, _ = bs.mark_done({}, [], "LENS", "70111309", "a@pk", "2026-10-29T10:00:00")
    v = bs.card_state(st["LENS"], "2026-10-29T09:00:00", [["70111309", "2026-10-29", 4.0]])
    assert v["done"]["state"] == "waiting" and v["done"]["po_found"]
    assert bs.card_state(None, "x", [])["done"] is None
