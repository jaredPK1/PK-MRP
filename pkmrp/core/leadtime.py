"""Realized purchase lead time, from PO history.

Realized = business days from PO creation to the last receipt, on lines
received in full. A line ordered deliberately early (its original due date
more than EARLY_FACTOR x PURLT_01 after creation) overstates the supplier's
lead time, so it is kept visible but left out of the statistics.

Per part: median and P80 over the window, the line count, the most recent
vendor, and the ratio of the median to PURLT_01. Parts with fewer than
MIN_LINES usable lines fall back to PURLT_01 and say so. A vendor-and-
commodity median exists (vendor_fallback=True) but is off: MAX has no
commodity field -- CLSCDE_01 is a one-letter class -- and a distributor's
median across class "B" gave the 370-day FPGA a lead time of 5 days.
"""

from collections import defaultdict
from statistics import median

from .calendar import as_date, workdays_between

MIN_LINES = 3
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


def realized(po_history, purchase_lt, part_class=None, vendor_fallback=False):
    """{part: {...}} with median, p80, lines, early_lines, vendor, purlt, ratio,
    source}. `purchase_lt` is {part: PURLT_01}; `part_class` {part: CLSCDE_01}
    groups the fallback by vendor *and* commodity class."""
    part_class = part_class or {}
    per_part = defaultdict(list)
    early = defaultdict(int)
    vendor_last = {}
    vendor_days = defaultdict(list)
    rows = po_history.sort_values("created").itertuples(index=False)
    for r in rows:
        created, last = as_date(r.created), as_date(r.last_receipt)
        if not created or not last or last < created:
            continue
        cur = float(r.qty_current or 0)
        if cur <= 0 or float(r.qty_received or 0) < FULL_RECEIPT * cur:
            continue
        days = workdays_between(created, last)
        plt = float(purchase_lt.get(r.part) or 0)
        org = as_date(r.org_due)
        if plt > 0 and org and workdays_between(created, org) > EARLY_FACTOR * plt:
            early[r.part] += 1
            continue
        per_part[r.part].append(days)
        vendor_days[(r.vendor_id, part_class.get(r.part, ""))].append(days)
        vendor_last[r.part] = r.vendor_id

    vendor_median = {k: median(d) for k, d in vendor_days.items() if len(d) >= MIN_GROUP_LINES}
    out = {}
    for part in set(per_part) | set(early) | set(purchase_lt):
        days = per_part.get(part, [])
        plt = float(purchase_lt.get(part) or 0)
        vendor = vendor_last.get(part)
        if len(days) >= MIN_LINES:
            med, p80, source = median(days), _p80(days), f"realized ({len(days)} lines)"
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
