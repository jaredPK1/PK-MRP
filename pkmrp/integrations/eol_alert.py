"""Email when a part goes obsolete: new items on the EOL watch, once each.

After every research tick the watch list is compared with the parts already
alerted (research_state.json "eol_alerted"); parts newly obsolete, end of
life, last-time buy or not recommended for new designs go out in one email
through pk-notify. Production only (SCHEDULER_ENABLED=1), like the weekly
email. Recipients: mrp_settings 'eol_alert_recipients', default Jared and
Patrick (Engineering). A part is marked alerted only once the email is sent.
"""

import html

from .. import notify

ALERT_KINDS = ("obsolete", "eol", "last_time_buy", "nrnd")
RECIPIENTS_KEY = "eol_alert_recipients"
DEFAULT_RECIPIENTS = ["jared.green@pkinetics.com", "patrick.tourreau@pkinetics.com"]
WORDS = {
    "obsolete": "Obsolete",
    "eol": "End of life",
    "last_time_buy": "Last-time buy",
    "nrnd": "Not recommended for new designs",
}


def key(item):
    return f"{item['part']}|{item['kind']}"


def new_items(items, alerted):
    """Watch items worth an email that haven't had one."""
    return [i for i in items if i["kind"] in ALERT_KINDS and key(i) not in alerted]


def _money(v):
    return f"${v:,.0f}"


def render(items, base_url):
    rows = []
    for i in items:
        sig = (i.get("signals") or [{}])[0]
        last = i.get("last_order")
        link = f' <a href="{html.escape(sig["link"])}">source</a>' if sig.get("link") else ""
        rows.append(
            "<tr>"
            f"<td style='padding:8px 10px;border-top:1px solid #eef0f2;vertical-align:top;'>"
            f"<b style='font-family:monospace;'>{html.escape(i['part'])}</b><br>"
            f"<span style='color:#6b7280;'>{html.escape((i.get('description') or '').capitalize())}</span></td>"
            f"<td style='padding:8px 10px;border-top:1px solid #eef0f2;vertical-align:top;'>"
            f"<b style='color:#c2410c;'>{WORDS.get(i['kind'], i['kind'])}</b>"
            + (f"<br>last order {last}" if last else "")
            + (
                f"<br>use {html.escape(' / '.join(i['replacements'][:2]))}"
                if i.get("replacements")
                else ""
            )
            + "</td>"
            f"<td style='padding:8px 10px;border-top:1px solid #eef0f2;vertical-align:top;font-size:13px;'>"
            f"{html.escape(sig.get('source', ''))} {html.escape(sig.get('where', ''))}: "
            f"{html.escape((sig.get('detail') or '')[:200])}{link}</td>"
            f"<td style='padding:8px 10px;border-top:1px solid #eef0f2;vertical-align:top;font-size:13px;'>"
            f"in {html.escape(', '.join(i.get('systems', [])[:3]) or '—')}<br>"
            f"booked {i['booked']:g} · have {i['on_hand'] + i['on_order']:g}"
            + (f" · {i['cover_months']} mo cover" if i.get("cover_months") is not None else "")
            + "<br>"
            + (
                f"<b>last-time buy {i['ltb_qty']:g} ({_money(i['ltb_cost'])})</b>"
                if i.get("ltb_qty")
                else "covered by stock"
            )
            + "</td></tr>"
        )
    url = f"{base_url}/eol" if base_url else ""
    return (
        "<table role='presentation' width='100%' cellpadding='0' cellspacing='0' "
        "style='font-family:Segoe UI,Arial,sans-serif;font-size:14px;color:#14181d;max-width:860px;'>"
        "<tr><td style='padding:18px 10px 6px;font-size:18px;font-weight:700;'>"
        f"{len(items)} part{'s' if len(items) != 1 else ''} going obsolete</td></tr>"
        "<tr><td style='padding:0 10px 10px;color:#3a4049;'>PK-MRP's EOL watch found these in distributor "
        "lifecycle data, supplier notices or maker news. Last-time buy = booked orders plus two years at "
        "the yearly rate, less stock and open POs — a starting point for Engineering and purchasing, "
        "not an order.</td></tr>"
        "<tr><td><table role='presentation' width='100%' cellpadding='0' cellspacing='0'>"
        "<tr style='color:#6b7280;font-size:12px;text-align:left;'><th style='padding:4px 10px;'>Part</th>"
        "<th style='padding:4px 10px;'>What</th><th style='padding:4px 10px;'>Where we heard</th>"
        "<th style='padding:4px 10px;'>Impact</th></tr>"
        + "".join(rows)
        + "</table></td></tr>"
        + (
            f"<tr><td style='padding:14px 10px;'><a href='{url}' style='color:#007a61;font-weight:700;'>"
            "Open the EOL watch</a></td></tr>"
            if url
            else ""
        )
        + "</table>"
    )


def send(items, recipients, base_url):
    """(sent_to, error)."""
    n = len(items)
    title = (
        f"EOL alert: {items[0]['part']} {WORDS.get(items[0]['kind'], '').lower()}"
        if n == 1
        else f"EOL alert: {n} parts going obsolete"
    )
    summary = "; ".join(f"{i['part']} {WORDS.get(i['kind'], i['kind']).lower()}" for i in items[:6])
    return notify.fire(
        "eol_alert",
        title,
        recipients,
        summary=summary,
        html_body=render(items, base_url),
        detail_url=f"{base_url}/eol" if base_url else None,
        metadata={"parts": [i["part"] for i in items][:50]},
    )
