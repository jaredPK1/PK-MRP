"""Who is on a buy, and whether it is really done -- shared, and checked
against MAX.

Done used to be a fold in each person's browser: invisible to everyone else,
reset daily, and a stray key folded cards nobody had placed. Now:

  * owner  -- who is working the buy (Chad / Rob / Aaron), picked on the card;
  * done   -- marked by a person, optionally with the PO number;
  * check  -- after each plan, reconcile() asks MAX's answer: the buy is gone
              from a plan made after it was marked (a PO went in, or the need
              went away) -> confirmed; still there -> "no PO in MAX yet", and
              the card comes back flagged.

Stored as two PK_Ops settings: buy_status {part: {...}} (the live state) and
buy_log [entry] (every Done, kept). Pure.
"""

import secrets

DEFAULT_BUYERS = ("Chad", "Rob", "Aaron")
LOG_CAP = 3000


def set_owner(status, part, owner, by, at):
    """status with `owner` on `part` ('' clears it)."""
    out = {k: dict(v) for k, v in status.items()}
    cur = out.setdefault(part, {})
    if owner:
        cur.update(owner=owner, owner_by=by, owner_at=at)
    else:
        for k in ("owner", "owner_by", "owner_at"):
            cur.pop(k, None)
    if not cur:
        out.pop(part)
    return out


def mark_done(status, log, part, po, by, at, buy=None):
    """(status, log) with `part` marked done by `by`; logs it."""
    po = (po or "").strip().upper()[:20]
    entry = {
        "id": secrets.token_hex(4), "part": part, "po": po, "by": by, "at": at,
        "owner": (status.get(part) or {}).get("owner", ""),
        "description": (buy or {}).get("description", ""),
        "qty": (buy or {}).get("qty"), "vendor": (buy or {}).get("vendor", ""),
        "check": "waiting", "checked_at": None,
    }
    out = {k: dict(v) for k, v in status.items()}
    out.setdefault(part, {})["done"] = {"id": entry["id"], "po": po, "by": by, "at": at}
    return out, [*log, entry][-LOG_CAP:]


def undo_done(status, log, part, by, at):
    """(status, log) with `part`'s Done taken back (logged as undone)."""
    out = {k: dict(v) for k, v in status.items()}
    done = (out.get(part) or {}).pop("done", None)
    if part in out and not out[part]:
        out.pop(part)
    if not done:
        return out, log
    log = [
        {**e, "check": "undone", "checked_at": at, "undone_by": by} if e["id"] == done["id"] else e
        for e in log
    ]
    return out, log


def reconcile(status, log, buy_parts, generated_at):
    """After a plan: confirm or flag every Done marked before that plan, and
    clear owners on buys the plan no longer has. (status, log, changed)."""
    out, changed = {}, False
    checks = {}
    for part, st in status.items():
        st = dict(st)
        done = st.get("done")
        if done and done["at"] < generated_at:
            if part not in buy_parts:  # MAX covers it now
                checks[done["id"]] = "confirmed"
                st.pop("done")
                changed = True
            elif done.get("check") != "no_po":
                checks[done["id"]] = "no_po"
                st["done"] = {**done, "check": "no_po"}
                changed = True
        if part not in buy_parts and "done" not in st and st.get("owner"):
            for k in ("owner", "owner_by", "owner_at"):
                st.pop(k, None)
            changed = True
        if st:
            out[part] = st
    if checks:
        log = [
            {**e, "check": checks[e["id"]], "checked_at": generated_at}
            if e["id"] in checks and e.get("check") not in ("undone",) else e
            for e in log
        ]
    return out, log, changed


def card_state(st, generated_at, recent_pos):
    """What a card shows: owner, and done -> ('waiting'|'no_po', po, found)."""
    st = st or {}
    done = st.get("done")
    view = {"owner": st.get("owner", ""), "done": None}
    if done:
        po = done.get("po", "")
        state = "no_po" if done.get("check") == "no_po" or done["at"] < generated_at else "waiting"
        view["done"] = {**done, "state": state,
                        "po_found": bool(po) and any(p[0] == po for p in recent_pos)}
    return view
