"""Send through pk-notify, PK's delivery hub (email / Teams).

POST {PK_NOTIFY_URL} with Bearer PK_NOTIFY_TOKEN; recipients are
@pkinetics.com emails. Contract: pk-server-manager/PK_NOTIFICATIONS.md.
Standard library only.
"""

import json
import os
import urllib.error
import urllib.request

SOURCE_APP = "pk-mrp"
DEFAULT_URL = "http://pk-notify:8000/pk-notify/api/notify"


def enabled():
    return bool(os.environ.get("PK_NOTIFY_TOKEN"))


def fire(event_type, title, recipients, summary="", html_body=None, detail_url=None,
         metadata=None, timeout=20):
    """(sent_to, error text or ''). Blocks until pk-notify answers."""
    to = sorted({(r or "").strip().lower() for r in recipients if r and "@" in r})
    if not to:
        return [], "no recipients"
    token = os.environ.get("PK_NOTIFY_TOKEN", "")
    if not token:
        return [], "pk-notify not configured (PK_NOTIFY_TOKEN missing)"
    payload = {
        "event_type": f"{SOURCE_APP}.{event_type}",
        "source_app": SOURCE_APP,
        "title": title,
        "summary": summary,
        "html_body": html_body,
        "detail_url": detail_url,
        "recipients": [{"email": r} for r in to],
        "metadata": metadata or {},
        "force_immediate": True,
    }
    req = urllib.request.Request(
        os.environ.get("PK_NOTIFY_URL", DEFAULT_URL),
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 -- internal URL
            if resp.status >= 300:
                return [], f"HTTP {resp.status}"
            body = json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as exc:
        return [], f"HTTP {exc.code}: {exc.read()[:300].decode(errors='replace')}"
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return [], str(exc)[:300]
    dropped = {d.get("email", d) if isinstance(d, dict) else d for d in body.get("dropped_recipients") or []}
    return [r for r in to if r not in dropped], ""
