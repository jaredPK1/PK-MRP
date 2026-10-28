"""One planning run: extract from MAX, plan, return everything a page or a
report needs. The only place extract (I/O) meets core (pure)."""

import time
from datetime import date, timedelta

from .core import demand as demand_mod
from .core import leadtime, supply
from .core.bom import children_map
from .core.netting import Part, plan
from .core.settings import PlanSettings
from .db import extract


def build_plan(erp, settings=None, today=None, history_months=24):
    settings = settings or PlanSettings()
    today = today or date.today()
    timings = {}

    def timed(name, fn, *a):
        t = time.time()
        out = fn(*a)
        timings[name] = round(time.time() - t, 2)
        return out

    parts_df = timed("parts", extract.parts, erp)
    bom_df = timed("bom", extract.bom, erp)
    so_df = timed("open_so_lines", extract.open_so_lines, erp)
    stock_df = timed("stock", extract.stock, erp)
    po_df = timed("open_pos", extract.open_pos, erp)
    wo_df = timed("open_wos", extract.open_wos, erp)
    req_df = timed("wo_requirements", extract.wo_requirements, erp)
    hist_df = timed(
        "po_history", extract.po_history, erp, today - timedelta(days=round(history_months * 30.44))
    )

    parts = {
        r.part: Part(
            r.part,
            r.type,
            r.description,
            r.purchase_lt_bdays,
            r.mfg_lt_wdays,
            r.min_qty,
            r.mult_qty,
            r.unit_cost,
            r.buyer,
        )
        for r in parts_df.itertuples(index=False)
    }
    kept = bom_df[bom_df["type_code"].isin(settings.bom_type_codes)]
    skipped_codes = (
        bom_df.loc[~bom_df["type_code"].isin(settings.bom_type_codes), "type_code"]
        .value_counts()
        .to_dict()
    )
    children = children_map(zip(kept["parent"], kept["component"], kept["qty_per"], strict=True))

    stock = supply.on_hand(stock_df)
    receipts = supply.open_receipts(po_df, wo_df, today)
    part_types = {p: v.type for p, v in parts.items()}
    so_demand, worklists = demand_mod.backlog_demand(
        so_df, settings, set(children), stock, part_types
    )
    wo_demand = demand_mod.wo_requirement_demand(req_df, today)

    buy = {p for p, v in parts.items() if v.type in settings.buy_types}
    classes = dict(zip(parts_df["part"], parts_df["class_code"], strict=True))
    lt_stats = leadtime.realized(
        hist_df, {p: parts[p].purchase_lt for p in buy}, {p: classes.get(p, "") for p in buy}
    )
    t = time.time()
    result = plan(
        parts,
        children,
        so_demand + wo_demand,
        stock,
        receipts,
        settings,
        today,
        leadtime.for_netting(lt_stats),
    )
    timings["netting"] = round(time.time() - t, 2)

    return {
        "today": today,
        "settings": settings,
        "parts": parts,
        "children": children,
        "stock": stock,
        "receipts": receipts,
        "lead_times": lt_stats,
        "result": result,
        "worklists": worklists,
        "bom_codes_skipped": skipped_codes,
        "timings": timings,
        "counts": {
            "so_lines": len(so_df),
            "so_demand": len(so_demand),
            "wo_requirements": len(wo_demand),
            "receipts": len(receipts),
            "planned": len(result.planned),
            "exceptions": len(result.exceptions),
        },
    }
