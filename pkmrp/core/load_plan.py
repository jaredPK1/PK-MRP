"""Parked orders planned into Load Plan months with room.

Order Admin parks orders with no build slot on 2032-34 year-end dates
(CURDUE_28). Their CUSDUE_28 -- the date PK-MRP plans on -- still holds the
customer's ask, mostly late 2026 to mid 2027, so without this the plan treats
$14M of unslotted orders as due now. Control Tower's Load Plan
(pk-ops-tower blueprints/load_plan_data.py) caps each ship month at $5M of
revenue and a unit cap per model; Jared (2026-11-03): "use the load plan in
ops tower to plan the orders in where there is room".

The rule is the Load Plan's own: an order that would break a cap goes to the
next month with room. Counting matches it so the room here is the room on that
page: revenue = open qty x unit price, intercompany left out; units = open qty
on 01- and FLS lines by model prefix; a dated line sits in its CURDUE month
(past due counts in the current month, which is where it would ship).

Parked orders are placed oldest order first, never before the customer's
month or the current one, as a whole order when it fits in one month, else
line by line, a line bigger than a whole month split across months. Placed
lines get the first of their month as the demand date (`settings.demand_date`)
and keep CURDUE, so Fix in MAX still lists them as needing a real date.
Intercompany orders take no room and are left as they are.

Caps are copied from the Load Plan's defaults; edits made on that page don't
flow here yet. Pure.
"""

from collections import defaultdict
from datetime import date

import pandas as pd

from .calendar import as_date

REVENUE = "revenue"

# (model, part prefixes, units per month) -- pk-ops-tower load_plan_data.MODELS.
MODEL_CAPS = (
    ("2600", ("01-26",), 2),
    ("2550", ("01-25",), 1),
    ("2300", ("01-2300",), 5),
    ("2302", ("01-2302",), 5),
    ("8000", ("01-81",), 8),
    ("8000i", ("01-08",), 5),
    ("1050", ("01-10",), 5),
    ("1100", ("01-11",), 4),
    ("2880", ("01-28",), 2),
    ("2920", ("01-29",), 2),
    ("FLS", ("FLS",), 2),
    ("Cleaver", ("01-03",), 40),
)
_PREFIXES = sorted(((p, m) for m, ps, _ in MODEL_CAPS for p in ps), key=lambda x: -len(x[0]))


def model_of(part):
    pn = (part or "").strip().upper()
    for prefix, model in _PREFIXES:
        if pn.startswith(prefix):
            return model
    return None


def caps(settings):
    return {REVENUE: settings.load_revenue_cap, **{m: c for m, _, c in MODEL_CAPS}}


def _ym(d):
    return d.year * 12 + d.month - 1


def _first_of(ym):
    return date(ym // 12, ym % 12 + 1, 1)


def _counts(r, model):
    """{metric: amount} one line puts against the caps."""
    qty = float(r.qty_due or 0)
    price = r.unit_price if r.unit_price == r.unit_price else 0.0
    out = {REVENUE: float(price or 0) * qty}
    if model:
        out[model] = qty
    return {k: v for k, v in out.items() if v}


def _intercompany(r):
    t = getattr(r, "customer_type", "")
    return isinstance(t, str) and t.strip().upper() == "X"


def slot(so_df, settings, today):
    """(so_df with parked lines dated into Load Plan months, summary)."""
    if so_df.empty:
        return so_df, {"placed": [], "unplaced": [], "months": {}}
    cap = caps(settings)
    now = _ym(today)
    horizon = now + settings.load_horizon_months
    booked = defaultdict(lambda: defaultdict(float))  # ym -> metric -> amount
    parked = defaultdict(list)  # so -> [(index, row)]
    for i, r in zip(so_df.index, so_df.itertuples(index=False), strict=True):
        if r.part == "DETAILS" or _intercompany(r):
            continue
        cur = as_date(r.cur_due)
        if cur and cur.year >= settings.unscheduled_from_year:
            parked[r.so].append((i, r))
        elif cur:
            for k, v in _counts(r, model_of(r.part)).items():
                booked[max(_ym(cur), now)][k] += v

    def fits(ym, add):
        return all(booked[ym][k] + v <= cap[k] + 1e-6 for k, v in add.items())

    def take(ym, add):
        for k, v in add.items():
            booked[ym][k] += v

    def order_date(rows):
        d = as_date(getattr(rows[0][1], "order_date", None))
        return d or date.max

    placed, unplaced = [], []
    new_rows = {}  # index -> [(ym, qty)]
    for so in sorted(parked, key=lambda s: (order_date(parked[s]), s)):
        rows = parked[so]
        asks = [as_date(getattr(r, settings.demand_date, None)) for _, r in rows]
        start = max([now] + [_ym(a) for a in asks if a and a.year < settings.unscheduled_from_year])
        lines = [(i, r, _counts(r, model_of(r.part))) for i, r in rows]
        whole = defaultdict(float)
        for _, _, c in lines:
            for k, v in c.items():
                whole[k] += v
        ym = next((m for m in range(start, horizon) if fits(m, whole)), None)
        if ym is not None:
            take(ym, whole)
            for i, r, _ in lines:
                new_rows[i] = [(ym, float(r.qty_due))]
            placed.append({"so": so, "customer": rows[0][1].customer, "months": [_first_of(ym)],
                           "value": round(whole.get(REVENUE, 0.0), 2), "split": False})
            continue
        # Too big for one month: line by line, splitting a line across months.
        months = set()
        for i, r, c in lines:
            qty = float(r.qty_due)
            per = {k: v / qty for k, v in c.items()}
            parts, left, m = [], qty, start
            while left > 1e-9 and m < horizon:
                room = left
                for k, v in per.items():
                    room = min(room, max(cap[k] - booked[m][k], 0.0) / v)
                n = min(left, float(int(room + 1e-9)) if room < left else left)
                if n <= 0 and per and all(booked[m][k] == 0 for k in per):
                    n = 1.0  # one unit worth more than a whole month: alone in an empty month
                if n > 0:
                    take(m, {k: v * n for k, v in per.items()})
                    parts.append((m, n))
                    months.add(m)
                    left -= n
                m += 1
            if left > 1e-9:
                unplaced.append({"so": so, "line": r.line, "part": r.part, "qty": left})
                if parts:  # the rest rides in the last month rather than vanish
                    parts[-1] = (parts[-1][0], parts[-1][1] + left)
            new_rows[i] = parts  # [] = no room in the horizon: stays parked
        if not months:
            continue
        placed.append({"so": so, "customer": rows[0][1].customer,
                       "months": [_first_of(m) for m in sorted(months)],
                       "value": round(whole.get(REVENUE, 0.0), 2), "split": True})

    out = []
    col = settings.demand_date
    for i, r in so_df.iterrows():
        if i not in new_rows:
            out.append(r)
            continue
        if not new_rows[i]:
            x = r.copy()
            x[col] = r["cur_due"]  # still parked: the unscheduled worklist
            out.append(x)
            continue
        for ym, qty in new_rows[i]:
            x = r.copy()
            x[col] = pd.Timestamp(_first_of(ym))
            x["qty_due"] = qty
            x["load_month"] = _first_of(ym).isoformat()[:7]
            out.append(x)
    df = pd.DataFrame(out).reset_index(drop=True)
    if "load_month" not in df:
        df["load_month"] = None
    by_month = defaultdict(lambda: {"orders": 0, "value": 0.0})
    for p in placed:
        b = by_month[p["months"][0].isoformat()[:7]]
        b["orders"] += 1
        b["value"] += p["value"]
    return df, {"placed": placed, "unplaced": unplaced, "months": dict(sorted(by_month.items()))}
