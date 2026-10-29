"""Part notes: what people know about a part that MAX doesn't say.

"Engineering is working on a replacement", "obsolete", "ECN being created" --
said once, kept on the part, and shown wherever the part appears, so nobody
has to flag it again next plan. A note stays until someone removes it. Only
"hold" changes what buyers see: a held part comes off every buy list (the
plan itself is untouched).

Stored as one PK_Ops setting, {part: [note, ...]}, newest last. Pure.
"""

import secrets

# (code, words). "other" needs text; the rest may have it.
TAGS = (
    ("replacement", "Engineering working on a replacement"),
    ("obsolete", "Obsolete / end of life"),
    ("ecn", "ECN being created"),
    ("hold", "Hold — don't buy yet"),
    ("supplier", "Supplier problem"),
    ("other", "Note"),
)
TAG_WORDS = dict(TAGS)
# Short words for the chip next to a part number.
TAG_SHORT = {
    "replacement": "replacement coming",
    "obsolete": "obsolete",
    "ecn": "ECN coming",
    "hold": "on hold",
    "supplier": "supplier problem",
    "other": "note",
}


def add(notes, part, tag, text, by, at):
    """notes with one more note on `part`; raises ValueError when it's not a
    note anyone could use."""
    text = (text or "").strip()[:500]
    if tag not in TAG_WORDS:
        raise ValueError("Pick what kind of note it is.")
    if tag == "other" and not text:
        raise ValueError("Write the note.")
    note = {"id": secrets.token_hex(4), "tag": tag, "text": text, "by": by, "at": at}
    return {**notes, part: [*notes.get(part, []), note]}


def remove(notes, part, note_id):
    """notes without that note; a part with none left drops out."""
    left = [n for n in notes.get(part, []) if n["id"] != note_id]
    out = {k: v for k, v in notes.items() if k != part}
    if left:
        out[part] = left
    return out


def listing(notes, descriptions, tag=None):
    """Rows for the Notes page, newest note first: one per note."""
    rows = [
        {**n, "part": p, "description": descriptions.get(p, "")}
        for p, ns in notes.items()
        for n in ns
        if not tag or n["tag"] == tag
    ]
    return sorted(rows, key=lambda r: r["at"], reverse=True)
