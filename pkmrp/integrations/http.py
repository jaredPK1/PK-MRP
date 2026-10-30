"""Small JSON-over-HTTPS helpers on the standard library (no extra deps)."""

import json
import urllib.error
import urllib.parse
import urllib.request

TIMEOUT = 30


class HttpError(RuntimeError):
    def __init__(self, status, body):
        super().__init__(f"HTTP {status}: {body[:300]}")
        self.status = status


def request(method, url, headers=None, body=None, form=None, timeout=TIMEOUT):
    """Returns parsed JSON (or {} for an empty body). `body` is sent as JSON,
    `form` as application/x-www-form-urlencoded."""
    headers = dict(headers or {})
    data = None
    if form is not None:
        data = urllib.parse.urlencode(form).encode()
        headers.setdefault("Content-Type", "application/x-www-form-urlencoded")
    elif body is not None:
        data = json.dumps(body).encode()
        headers.setdefault("Content-Type", "application/json")
    headers.setdefault("Accept", "application/json")
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        raise HttpError(exc.code, exc.read().decode("utf-8", "replace")) from exc
    return json.loads(raw) if raw.strip() else {}


def client_credentials_token(url, client_id, client_secret, **extra):
    """OAuth2 client-credentials token (DigiKey, Nexar, Microsoft Graph)."""
    form = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
        **extra,
    }
    return request("POST", url, form=form)["access_token"]
