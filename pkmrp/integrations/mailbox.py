"""The purchasing mailbox, through Microsoft Graph (application access).

Reads messages received since the last check, keeps the ones that look like
a supplier notice (PCN, EOL, last-time buy, discontinuation, obsolescence),
and hands those to ai.py to pull out what the notice says. IT grants the app
Mail.Read and limits it to the one mailbox with an application access policy
(deploy/RESEARCH_SETUP.md).
"""

import html
import os
import re
import urllib.parse

from .http import client_credentials_token, request

NOTICE_WORDS = re.compile(
    r"\b(pcn|eol|end[- ]of[- ]life|last[- ]time[- ]buy|ltb|discontinu\w*|obsolet\w*|"
    r"product change notice|product discontinuance|pdn|not recommended for new designs|nrnd|"
    r"end of production|final order|lifetime buy)\b",
    re.I,
)


def looks_like_notice(subject, text):
    return bool(NOTICE_WORDS.search(subject or "") or NOTICE_WORDS.search((text or "")[:6000]))


def html_to_text(body):
    t = re.sub(r"(?is)<(script|style).*?</\1>", " ", body or "")
    t = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>", "\n", t)
    t = re.sub(r"<[^>]+>", " ", t)
    t = html.unescape(t).replace("\xa0", " ")
    return re.sub(r"[ \t\r\f\v]+", " ", re.sub(r"\n\s*\n+", "\n\n", t)).strip()


class Mailbox:
    GRAPH = "https://graph.microsoft.com/v1.0"

    def __init__(self, tenant, client_id, secret, mailbox):
        self.tenant, self.client_id, self.secret, self.mailbox = tenant, client_id, secret, mailbox

    @classmethod
    def from_env(cls):
        vals = [
            os.environ.get(k)
            for k in (
                "GRAPH_TENANT_ID",
                "GRAPH_CLIENT_ID",
                "GRAPH_CLIENT_SECRET",
                "PURCHASING_MAILBOX",
            )
        ]
        return cls(*vals) if all(vals) else None

    def _token(self):
        return client_credentials_token(
            f"https://login.microsoftonline.com/{self.tenant}/oauth2/v2.0/token",
            self.client_id,
            self.secret,
            scope="https://graph.microsoft.com/.default",
        )

    def messages_since(self, since_iso, limit=300):
        """[{id, subject, sender, received, text, web_link}] newest last."""
        token = self._token()
        params = {
            "$filter": f"receivedDateTime ge {since_iso}",
            "$orderby": "receivedDateTime asc",
            "$select": "id,subject,from,receivedDateTime,body,webLink,hasAttachments",
            "$top": "50",
        }
        url = (
            f"{self.GRAPH}/users/{urllib.parse.quote(self.mailbox)}/messages?"
            + urllib.parse.urlencode(params)
        )
        out = []
        while url and len(out) < limit:
            data = request(
                "GET",
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Prefer": 'outlook.body-content-type="text"',
                },
            )
            for m in data.get("value") or []:
                body = (m.get("body") or {}).get("content") or ""
                if (m.get("body") or {}).get("contentType") == "html":
                    body = html_to_text(body)
                out.append(
                    {
                        "id": m.get("id"),
                        "subject": m.get("subject") or "",
                        "sender": ((m.get("from") or {}).get("emailAddress") or {}).get("address")
                        or "",
                        "sender_name": ((m.get("from") or {}).get("emailAddress") or {}).get("name")
                        or "",
                        "received": m.get("receivedDateTime") or "",
                        "text": body,
                        "web_link": m.get("webLink") or "",
                        "attachments": bool(m.get("hasAttachments")),
                    }
                )
            url = data.get("@odata.nextLink")
        return out
