"""One planning run: extract from MAX, plan, return everything a page or a
report needs. The only place extract (I/O) meets core (pure)."""

import time
from datetime import date, timedelta

from .core import committed as committed_mod
from .core import consign, leadtime, segment, supply
from .core import demand as demand_mod
from .core import pipeline as pipeline_mod
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
    vendors_df = timed("vendors", extract.vendors, erp)
    pv_df = timed("part_vendors", extract.part_vendors, erp)
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
            r.yield_pct,
        )
        for r in parts_df.itertuples(index=False)
    }
    # Make parts explode their real components (type code N by default);
    # bought and outside parts explode only the kit PK consigns to the vendor.
    since = today - timedelta(days=round(history_months * 30.44))
    moves_df = timed("consign_moves", extract.consign_moves, erp, since)
    po_parts_df = timed("po_parts", extract.po_parts, erp, since - timedelta(days=365))
    sub_df = timed("subcontract_reqs", extract.subcontract_reqs, erp, since)
    consigned, consign_evidence = consign.consigned_edges(moves_df, po_parts_df, sub_df, bom_df)
    make = {p for p, v in parts.items() if v.type in settings.make_types}
    kept = bom_df[bom_df["type_code"].isin(settings.bom_type_codes) & bom_df["parent"].isin(make)]
    skipped_codes = (
        bom_df.loc[~bom_df["type_code"].isin(settings.bom_type_codes), "type_code"]
        .value_counts()
        .to_dict()
    )
    children = children_map(zip(kept["parent"], kept["component"], kept["qty_per"], strict=True))
    for parent, kit in consigned.items():
        if parent not in make:
            children[parent] = kit

    stock = supply.on_hand(stock_df)
    receipts = supply.open_receipts(po_df, wo_df, today)
    part_types = {p: v.type for p, v in parts.items()}
    so_demand, worklists = demand_mod.backlog_demand(
        so_df, settings, set(children), stock, part_types
    )
    wo_demand = demand_mod.wo_requirement_demand(req_df, today)
    sub_demand, sub_lines = consign.subcontract_demand(sub_df, today)

    buy = {p for p, v in parts.items() if v.type in settings.buy_types}
    classes = dict(zip(parts_df["part"], parts_df["class_code"], strict=True))
    lt_stats = leadtime.realized(
        hist_df, {p: parts[p].purchase_lt for p in buy}, {p: classes.get(p, "") for p in buy}
    )
    lead = leadtime.for_netting(lt_stats)

    # Who a buy would go to: the vendor on the part's most recent PO (any
    # status), else an approved source -- by name, as people know them.
    names = dict(zip(vendors_df["vendor_id"], vendors_df["name"], strict=True))
    vendor_of = {}
    for r in pv_df.itertuples(index=False):
        vendor_of.setdefault(r.part, r.vendor_id)
    for r in hist_df.sort_values("created").itertuples(index=False):
        if r.vendor_id:
            vendor_of[r.part] = r.vendor_id
    vendor_name = {p: names.get(v, v) for p, v in vendor_of.items()}

    def lead_of(p):
        return lead.get(p, (parts[p].purchase_lt if p in parts else 0, ""))[0]

    kit_demand = consign.open_kit_demand(po_df, consigned, sub_lines, lead_of, today)

    from .snapshot import so_rollups

    so_values, _ = so_rollups(so_df)
    t = time.time()
    gated = segment.gated_orders(so_df, children, settings, today)
    approved, used = segment.sources(pv_df, hist_df)
    segments = segment.classify(parts, lt_stats, approved, used, gated, so_values, settings)
    # Open receipts on these are bought ahead on purpose: "beyond_backlog",
    # never cancel candidates. Unproven long-lead parts too -- suggesting a
    # cancel on a part MAX says takes 300 days is the worse mistake.
    committed = {r["part"] for r in segments if r["segment"] in ("committed", "unproven_long")}
    timings["segment"] = round(time.time() - t, 2)
    t = time.time()
    result = plan(
        parts,
        children,
        so_demand + wo_demand + sub_demand + kit_demand,
        stock,
        receipts,
        settings,
        today,
        lead,
        committed,
    )
    timings["netting"] = round(time.time() - t, 2)

    # Committed supply: a 12-month plan for each committed part.
    committed_parts = [r["part"] for r in segments if r["segment"] == "committed"]
    months = committed_mod.monthly_requirement(
        committed_parts, so_df, children, parts, settings, today
    )
    # Book/Bill 2.0 pipeline: committed parts only, never the order-driven plan.
    pipeline = {"status": "off"}
    pipe_months = {}
    if settings.include_pipeline:
        try:
            lines_df = timed("pipeline_lines", extract.pipeline_lines, erp)
            pipe_df, pipeline = pipeline_mod.pipeline_demand(lines_df, set(parts), {}, settings)
            pipeline["status"] = "ok"
            pipe_months = committed_mod.monthly_requirement(
                committed_parts, pipe_df, children, parts, settings, today
            )
        except Exception as exc:  # noqa: BLE001 -- backlog-only plan still stands
            text = str(exc)
            no_access = any(
                k in text for k in ("permission", "not able to access", "denied", "4060", "916")
            )
            pipeline = {"status": "no_access" if no_access else "error", "error": text[:300]}
    for p, by_month in pipe_months.items():
        merged = months.setdefault(p, {})
        for m, q in by_month.items():
            merged[m] = merged.get(m, 0.0) + q
    open_by_part = {}
    for rc in receipts:
        if rc.kind == "po":
            open_by_part.setdefault(rc.part, []).append((rc.date, rc.qty, rc.ref))
    vendor_part = {}
    for r in pv_df.itertuples(index=False):
        if r.vendor_part and vendor_of.get(r.part) == r.vendor_id:
            vendor_part[r.part] = r.vendor_part
    committed_plans = []
    for p in committed_parts:
        cp = committed_mod.plan_part(
            p,
            parts[p],
            months.get(p, {}),
            lt_stats[p]["p80"],
            stock.get(p, 0.0),
            open_by_part.get(p, []),
            settings,
            today,
        )
        cp["vendor"] = vendor_name.get(p, "")
        cp["vendor_part"] = vendor_part.get(p, "")
        cp["buyer"] = parts[p].buyer
        cp["pipeline_12m"] = round(sum(pipe_months.get(p, {}).values()) * settings.growth_bias, 2)
        committed_plans.append(cp)

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
        "so_lines": so_df,
        "po_history": hist_df,
        "open_pos": po_df,
        "vendor_name": vendor_name,
        "segments": segments,
        "committed_plans": committed_plans,
        "pipeline": pipeline,
        "consigned": consigned,
        "consign_evidence": consign_evidence,
        "bom_codes_skipped": skipped_codes,
        "timings": timings,
        "counts": {
            "so_lines": len(so_df),
            "so_demand": len(so_demand),
            "wo_requirements": len(wo_demand),
            "subcontract_reqs": len(sub_demand),
            "open_po_kits": len(kit_demand),
            "consigned_pairs": len(consign_evidence),
            "receipts": len(receipts),
            "planned": len(result.planned),
            "exceptions": len(result.exceptions),
        },
    }
