"""The research loop: outside sources on their own intervals, within budgets.

Called after every hourly plan (snapshot.add_research). Each source runs
only when RESEARCH_ENABLED=1 and its keys are set, and only when it's due:

  distributors  every hour, a slice: parts not checked in 7 days, biggest
                yearly spend first, within each service's free quota
                (DigiKey ~1,000/day, Mouser ~1,000/day, Nexar 1,000 parts a
                month -> 200 a week here);
  mailbox       every hour: new mail since the last check, notice-like ones
                read by Claude;
  news          weekly: the makers behind the most booked parts, one web
                search each.

Results are cached in the data volume (distributor_cache.json,
eol_notices.json, eol_news.json); the EOL watch (eol.json) and catalog
price ideas (distributor_ideas.json) are rebuilt from the caches on every
call, so the pages work even when nothing new was fetched.
"""

import json
import os
from collections import defaultdict
from datetime import datetime, timedelta

from ..core import eol
from . import ai, distributors
from .mailbox import Mailbox, looks_like_notice

DIST_EVERY = timedelta(hours=1)
DIST_STALE = timedelta(days=7)
DIST_PER_TICK = {"digikey": 40, "mouser": 25, "nexar": 10}
NEXAR_PER_WEEK = 200
MAIL_EVERY = timedelta(hours=1)
MAIL_FIRST_DAYS = 90
MAIL_PER_TICK = 40
NEWS_EVERY = timedelta(days=7)
NEWS_MAKERS = 10
CATALOG_PCT = 0.15
CATALOG_MIN = 2000.0


def _load(data_dir, name, default):
    try:
        with open(os.path.join(data_dir, name), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def _save(data_dir, name, data):
    tmp = os.path.join(data_dir, f".{name}.tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, separators=(",", ":"), default=str)
    os.replace(tmp, os.path.join(data_dir, name))


def _due(state, key, every, now):
    last = state.get(key)
    return not last or now - datetime.fromisoformat(last) >= every


def enabled():
    return os.environ.get("RESEARCH_ENABLED", "0").strip() == "1"


def _annual(run):
    end = run["today"] + timedelta(days=365)
    out = defaultdict(float)
    for part, ds in run["result"].demands.items():
        out[part] = sum(d.qty for d in ds if d.date <= end)
    for rows in (run.get("vendor_prices") or {}).get("parts", {}).values():
        for r in rows:
            out[r["part"]] = max(out[r["part"]], r["ttm_qty"])
    return out


def candidates(run, annual):
    """[(part, lookup number)] worth a distributor check, biggest yearly spend first."""
    parts = run["parts"]
    mpns = run.get("mpns")
    if mpns is None or not len(mpns):
        return []
    first = {}
    for r in mpns.itertuples(index=False):
        rank = {"mpn_file": 0, "vendor_mpn": 1, "vendor_sku": 2}.get(r.source, 3)
        if r.part not in first or rank < first[r.part][0]:
            first[r.part] = (rank, r.mpn)
    out = []
    for part, (_rank, mpn) in first.items():
        info = parts.get(part)
        if not info or info.type not in ("B",):
            continue
        q = annual.get(part, 0.0) or run["stock"].get(part, 0.0)
        if q <= 0:
            continue
        out.append((q * float(info.unit_cost or 0.0), part, mpn))
    out.sort(reverse=True)
    return [(p, m) for _v, p, m in out]


def run_distributors(run, annual, data_dir, state, now):
    cache = _load(data_dir, "distributor_cache.json", {})
    cls = distributors.clients()
    status = {"state": "no_keys" if not cls else "ok", "checked": 0, "errors": []}
    if not cls or not _due(state, "dist_at", DIST_EVERY, now):
        return cache, status
    week = now.strftime("%G-W%V")
    used = state.setdefault("nexar_week", {})
    left = {c.name: DIST_PER_TICK.get(c.name, 10) for c in cls}
    if "nexar" in left:
        left["nexar"] = min(left["nexar"], max(NEXAR_PER_WEEK - used.get(week, 0), 0))
    for part, mpn in candidates(run, annual):
        if not any(left.values()):
            break
        c = cache.get(part) or {}
        if c.get("checked") and now - datetime.fromisoformat(c["checked"]) < DIST_STALE:
            continue
        offers = []
        for cl in cls:
            if left.get(cl.name, 0) <= 0:
                continue
            left[cl.name] -= 1
            if cl.name == "nexar":
                used[week] = used.get(week, 0) + 1
            try:
                offers += cl.lookup(mpn)
            except Exception as exc:  # noqa: BLE001 -- one bad lookup doesn't stop the rest
                status["errors"].append(f"{cl.name} {mpn}: {str(exc)[:120]}")
        cache[part] = {"checked": now.isoformat(timespec="minutes"), "mpn": mpn, "offers": offers}
        status["checked"] += 1
    state["dist_at"] = now.isoformat(timespec="minutes")
    status["errors"] = status["errors"][:10]
    _save(data_dir, "distributor_cache.json", cache)
    return cache, status


def run_mailbox(data_dir, state, now):
    store = _load(data_dir, "eol_notices.json", [])
    mb = Mailbox.from_env()
    if not mb:
        return store, {"state": "no_mailbox"}
    if not ai.available():
        return store, {"state": "no_ai_key"}
    if not _due(state, "mail_at", MAIL_EVERY, now):
        return store, {"state": "ok", "read": 0}
    since = state.get("mail_since") or (now - timedelta(days=MAIL_FIRST_DAYS)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    seen = {m["id"] for m in store}
    status = {"state": "ok", "read": 0, "notices": 0, "errors": []}
    try:
        msgs = mb.messages_since(since)
    except Exception as exc:  # noqa: BLE001
        return store, {"state": "error", "error": str(exc)[:300]}
    client = ai._client()
    for m in msgs:
        status["read"] += 1
        state["mail_since"] = m["received"] or since
        if m["id"] in seen or not looks_like_notice(m["subject"], m["text"]):
            continue
        if status["notices"] >= MAIL_PER_TICK:
            state["mail_since"] = m["received"]  # pick up from here next hour
            break
        try:
            n = ai.read_notice(m, client)
        except Exception as exc:  # noqa: BLE001
            status["errors"].append(f"{m['subject'][:60]}: {str(exc)[:120]}")
            continue
        store.append(
            {
                k: m[k]
                for k in (
                    "id",
                    "subject",
                    "sender",
                    "sender_name",
                    "received",
                    "web_link",
                    "attachments",
                )
            }
            | {"notice": n}
        )
        status["notices"] += 1
    state["mail_at"] = now.isoformat(timespec="minutes")
    status["errors"] = status["errors"][:10]
    _save(data_dir, "eol_notices.json", store)
    return store, status


def run_news(run, annual, data_dir, state, now):
    store = _load(data_dir, "eol_news.json", [])
    if not ai.available():
        return store, {"state": "no_ai_key"}
    if not _due(state, "news_at", NEWS_EVERY, now):
        return store, {"state": "ok", "searched": 0}
    mpns = run.get("mpns")
    parts = run["parts"]
    by_maker = defaultdict(list)
    if mpns is not None:
        for r in mpns.itertuples(index=False):
            if r.maker and annual.get(r.part, 0) > 0 and r.source != "vendor_sku":
                info = parts.get(r.part)
                by_maker[r.maker.strip().upper()].append(
                    (annual[r.part] * float(info.unit_cost or 0) if info else 0.0, r.mpn)
                )
    ranked = sorted(by_maker.items(), key=lambda kv: -sum(v for v, _m in kv[1]))[:NEWS_MAKERS]
    status = {"state": "ok", "searched": 0, "errors": []}
    client = ai._client()
    for maker, lst in ranked:
        pns = [m for _v, m in sorted(lst, reverse=True)][:25]
        try:
            found = ai.search_news(maker, pns, client)
        except Exception as exc:  # noqa: BLE001
            status["errors"].append(f"{maker}: {str(exc)[:120]}")
            continue
        store.append(
            {"maker": maker, "found_at": now.isoformat(timespec="minutes"), "notices": found}
        )
        status["searched"] += 1
    store = store[-200:]
    state["news_at"] = now.isoformat(timespec="minutes")
    _save(data_dir, "eol_news.json", store)
    return store, status


def catalog_ideas(cache, run, annual):
    """Catalog parts a distributor sells well under what PK last paid."""
    vp = run.get("vendor_prices") or {}
    paid = {}
    for vid, rows in vp.get("parts", {}).items():
        for r in rows:
            prev = paid.get(r["part"])
            if prev is None or str(r["last_date"]) > str(prev[2]):
                paid[r["part"]] = (r["last_price"], vid, r["last_date"], r["last_po"])
    names = run.get("vendor_names_by_id") or {}
    out = []
    for part, c in cache.items():
        if part not in paid:
            continue
        qty = annual.get(part, 0.0)
        if not qty:
            continue
        price, vid, _d, po = paid[part]
        best = None
        for o in c.get("offers") or []:
            p = distributors.price_at(o.get("breaks") or [], qty)
            if p and o.get("stock", 0) > 0 and (best is None or p < best[0]):
                best = (p, o)
        if not best or best[0] > price * (1 - CATALOG_PCT):
            continue
        saving = (price - best[0]) * qty
        if saving < CATALOG_MIN:
            continue
        o = best[1]
        info = run["parts"].get(part)
        out.append(
            {
                "kind": "catalog",
                "part": part,
                "description": info.description if info else "",
                "vendor_id": vid,
                "vendor": names.get(vid, vid),
                "to_vendor": o.get("source", ""),
                "saving": round(saving, 2),
                "evidence": {
                    "now_price": price,
                    "now_po": po,
                    "alt_price": best[0],
                    "sku": o.get("sku"),
                    "mpn": o.get("mpn"),
                    "stock": o.get("stock"),
                    "url": o.get("url"),
                    "checked": c.get("checked"),
                    "annual_qty": qty,
                },
                "what": f"{o.get('source', '').title()} lists {o.get('mpn', '')} at ${best[0]:,.2f} for {qty:g}/yr (in stock {o.get('stock', 0):,.0f}) vs ${price:,.2f} on PO {po}",
                "do": "Check it's the same part and rev (and packaging), then quote or buy from the catalog.",
            }
        )
    out.sort(key=lambda s: -s["saving"])
    return out


def tick(run, snap, data_dir):
    os.makedirs(data_dir, exist_ok=True)
    now = datetime.now()
    state = _load(data_dir, "research_state.json", {})
    annual = _annual(run)
    on = enabled()
    if on:
        cache, dist = run_distributors(run, annual, data_dir, state, now)
        notices, mail = run_mailbox(data_dir, state, now)
        news, news_st = run_news(run, annual, data_dir, state, now)
        _save(data_dir, "research_state.json", state)
    else:
        cache = _load(data_dir, "distributor_cache.json", {})
        notices = _load(data_dir, "eol_notices.json", [])
        news = _load(data_dir, "eol_news.json", [])
        dist = mail = news_st = {"state": "off"}

    on_order = defaultdict(float)
    for r in run["receipts"]:
        on_order[r.part] += r.qty
    mpn_rows = []
    if run.get("mpns") is not None:
        mpn_rows = [(r.part, r.mpn) for r in run["mpns"].itertuples(index=False)]
    watch = eol.build(
        cache,
        notices,
        news,
        mpn_rows,
        run["parts"],
        run["result"].demands,
        run["stock"],
        on_order,
        annual,
        run["today"],
    )
    _save(data_dir, "eol.json", _iso(watch))
    ideas = catalog_ideas(cache, run, annual)
    _save(data_dir, "distributor_ideas.json", _iso(ideas))
    return {
        "status": "on" if on else "off",
        "distributors": dist
        | {"cached": len(cache), "keys": [c.name for c in distributors.clients()]},
        "mailbox": mail
        | {"notices_total": sum(1 for m in notices if (m.get("notice") or {}).get("is_notice"))},
        "news": news_st | {"batches": len(news)},
        "eol_items": len(watch["items"]),
        "eol_counts": watch["counts"],
        "catalog_ideas": len(ideas),
        "ai_key": ai.available(),
        "last": {k: state.get(k) for k in ("dist_at", "mail_at", "news_at")},
    }


def _iso(v):
    if isinstance(v, dict):
        return {k: _iso(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_iso(x) for x in v]
    return v.isoformat() if hasattr(v, "isoformat") else v
