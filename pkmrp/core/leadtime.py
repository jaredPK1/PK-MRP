"""Realized purchase lead time, from PO history.

Realized = business days from PO creation to the last receipt, on lines
received in full. A line dated out on purpose -- its original due date more
than EARLY_FACTOR x the part's usual lead after creation, and it arrived by
that date, taking longer than usual -- shows only that the vendor paced
itself to a far date, not how long it
needs, so it is counted but left out of the statistics. One dated out that
arrived fast is good evidence and stays. "Usual" is the
median of all the part's lines over the ten years (robust to a few dated-out
ones), or PURLT_01 when there are too few lines; never PURLT_01 alone, which
is itself often the inflated number (69-0144-00G: PURLT 152, two POs dated
152 days out, arriving in 93 and 79 against a history of about 20). A line
that arrived *after* its asked date is a real slip and always counts.

Per part: median and P80 over the window, the line count, the most recent
vendor, and the ratio of the median to PURLT_01. Parts with fewer than
MIN_LINES usable lines in the window reach back for their most recent
older lines (up to DEEP_LINES): a spring bought once every year or two
still has a real history, just not a recent one. Only with fewer than
MIN_LINES ever do they fall back to PURLT_01, and say so. A vendor-and-
commodity median exists (vendor_fallback=True) but is off: MAX has no
commodity field -- CLSCDE_01 is a one-letter class -- and a distributor's
median across class "B" gave the 370-day FPGA a lead time of 5 days.
"""

from collections import defaultdict
from statistics import median

from .calendar import as_date, workdays_between

MIN_LINES = 3
DEEP_LINES = 5  # older lines used when the window has fewer than MIN_LINES
# A vendor+commodity fallback needs more evidence than a part's own history:
# a distributor's median across resistors says nothing about its FPGAs.
MIN_GROUP_LINES = 10
EARLY_FACTOR = 2.0
FULL_RECEIPT = 0.95  # received >= 95% of the current quantity counts as complete


def _p80(values):
    v = sorted(values)
    if not v:
        return None
    k = 0.8 * (len(v) - 1)
    lo, hi = int(k), min(int(k) + 1, len(v) - 1)
    return v[lo] + (v[hi] - v[lo]) * (k - lo)


def realized(po_history, purchase_lt, part_class=None, vendor_fallback=False, recent_since=None):
    """{part: {...}} with median, p80, lines, early_lines, vendor, purlt, ratio,
    source}. `purchase_lt` is {part: PURLT_01}; `part_class` {part: CLSCDE_01}
    groups the fallback by vendor *and* commodity class. Lines created before
    `recent_since` are used only for parts with too few recent ones."""
    part_class = part_class or {}
    lines = defaultdict(list)  # part -> [(created, asked, days, vendor)]
    for r in po_history.sort_values("created").itertuples(index=False):
        created, last = as_date(r.created), as_date(r.last_receipt)
        if not created or not last or last < created:
            continue
        cur = float(r.qty_current or 0)
        if cur <= 0 or float(r.qty_received or 0) < FULL_RECEIPT * cur:
            continue
        org = as_date(r.org_due)
        asked = workdays_between(created, org) if org and org >= created else None
        lines[r.part].append((created, asked, workdays_between(created, last), r.vendor_id))

    per_part = defaultdict(list)
    older = defaultdict(list)  # (created, days) before recent_since
    early = defaultdict(int)
    vendor_last = {}
    vendor_days = defaultdict(list)
    for part, ls in lines.items():
        plt = float(purchase_lt.get(part) or 0)
        usual = median(d for _, _, d, _ in ls) if len(ls) >= MIN_LINES else plt
        for created, asked, days, vendor in ls:
            if (
                usual > 0
                and asked is not None
                and asked > EARLY_FACTOR * usual
                and usual < days <= asked
            ):
                if not recent_since or created >= recent_since:
                    early[part] += 1
                continue
            if recent_since and created < recent_since:
                older[part].append((created, days))
                vendor_last.setdefault(part, vendor)
                continue
            per_part[part].append(days)
            vendor_days[(vendor, part_class.get(part, ""))].append(days)
            vendor_last[part] = vendor

    vendor_median = {k: median(d) for k, d in vendor_days.items() if len(d) >= MIN_GROUP_LINES}
    out = {}
    for part in set(per_part) | set(older) | set(early) | set(purchase_lt):
        days = per_part.get(part, [])
        plt = float(purchase_lt.get(part) or 0)
        vendor = vendor_last.get(part)
        since = None
        if len(days) < MIN_LINES and older.get(part):
            back = sorted(older[part])[-max(DEEP_LINES - len(days), 0) :]
            if len(days) + len(back) >= MIN_LINES:
                since = back[0][0]
                days = days + [d for _, d in back]
        if len(days) >= MIN_LINES:
            med, p80 = median(days), _p80(days)
            source = f"realized ({len(days)} lines" + (f" since {since.year})" if since else ")")
        elif (
            vendor_fallback and part_class.get(part) and (vendor, part_class[part]) in vendor_median
        ):
            med = p80 = vendor_median[(vendor, part_class[part])]
            source = f"vendor {vendor} / class {part_class[part]} median"
        elif plt > 0:
            med = p80 = plt
            source = "PURLT_01"
        else:
            continue
        out[part] = {
            "median": med,
            "p80": p80,
            "lines": len(days),
            "early_lines": early.get(part, 0),
            "vendor": vendor,
            "purlt": plt,
            "ratio": round(med / plt, 2) if plt > 0 else None,
            "source": source,
        }
    return out


def for_netting(stats, use="median"):
    """{part: (days, source)} for netting.plan()."""
    return {p: (s[use], s["source"]) for p, s in stats.items()}
