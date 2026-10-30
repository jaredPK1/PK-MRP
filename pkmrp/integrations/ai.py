"""Claude reads supplier notices and searches vendor news.

Two jobs, both structured:

  read_notice(email)  -> what a PCN / EOL / last-time-buy email says: the
                         maker, part numbers, notice type, last order and
                         last ship dates, and any replacement.
  search_news(maker, part numbers) -> the same shape for EOL / PCN news the
                         web search tool finds about a maker's parts.

Jared allowed the text to go as-is (2026-10-30): vendor emails can carry
prices; nothing about PK customers is sent. Server-side refusal fallback is
on (fallbacks="default"), so a declined request is retried on another model
inside the same call.
"""

import json
import os

MODEL = os.environ.get("RESEARCH_MODEL", "claude-opus-5-5")
FALLBACK_BETA = "server-side-fallback-2026-07-01"

NOTICE_SCHEMA = {
    "type": "object",
    "properties": {
        "is_notice": {"type": "boolean"},
        "kind": {
            "type": "string",
            "enum": ["eol", "last_time_buy", "nrnd", "pcn", "price", "other"],
        },
        "maker": {"type": "string"},
        "part_numbers": {"type": "array", "items": {"type": "string"}},
        "last_order_date": {"type": "string"},
        "last_ship_date": {"type": "string"},
        "replacements": {"type": "array", "items": {"type": "string"}},
        "summary": {"type": "string"},
    },
    "required": [
        "is_notice",
        "kind",
        "maker",
        "part_numbers",
        "last_order_date",
        "last_ship_date",
        "replacements",
        "summary",
    ],
    "additionalProperties": False,
}

NEWS_SCHEMA = {
    "type": "object",
    "properties": {
        "notices": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {
                        "type": "string",
                        "enum": ["eol", "last_time_buy", "nrnd", "pcn", "other"],
                    },
                    "part_numbers": {"type": "array", "items": {"type": "string"}},
                    "last_order_date": {"type": "string"},
                    "replacements": {"type": "array", "items": {"type": "string"}},
                    "summary": {"type": "string"},
                    "source_url": {"type": "string"},
                    "published": {"type": "string"},
                },
                "required": [
                    "kind",
                    "part_numbers",
                    "last_order_date",
                    "replacements",
                    "summary",
                    "source_url",
                    "published",
                ],
                "additionalProperties": False,
            },
        },
    },
    "required": ["notices"],
    "additionalProperties": False,
}

NOTICE_SYSTEM = (
    "You read emails from suppliers to a manufacturer's purchasing team. Decide whether the email "
    "is a supplier notice about a product's availability or change: end of life (eol), last-time "
    "buy, not recommended for new designs (nrnd), a product/process change notice (pcn), or a "
    "price change. Extract only what the email states. Dates as YYYY-MM-DD, or an empty string "
    "if not stated. Part numbers exactly as written (manufacturer or distributor numbers). "
    "Summary: one or two plain sentences a buyer can act on. Marketing, order confirmations and "
    "shipping notices are not notices (is_notice false, kind other)."
)


def available():
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def _client():
    import anthropic

    return anthropic.Anthropic()


def _text(resp):
    return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")


def _structured(client, system, content, schema, effort="low", max_tokens=4000):
    resp = client.beta.messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        betas=[FALLBACK_BETA],
        fallbacks="default",
        system=system,
        output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
        messages=[{"role": "user", "content": content}],
    )
    if resp.stop_reason == "refusal":
        raise RuntimeError("declined by the model")
    return json.loads(_text(resp))


def read_notice(msg, client=None):
    """msg: {subject, sender, sender_name, received, text} -> NOTICE_SCHEMA dict."""
    client = client or _client()
    body = (msg.get("text") or "")[:60000]
    content = (
        f"From: {msg.get('sender_name', '')} <{msg.get('sender', '')}>\n"
        f"Received: {msg.get('received', '')}\nSubject: {msg.get('subject', '')}\n\n{body}"
    )
    return _structured(client, NOTICE_SYSTEM, content, NOTICE_SCHEMA)


def search_news(maker, part_numbers, client=None, max_searches=4):
    """Web search for EOL / PCN news on a maker's parts -> [notice]."""
    client = client or _client()
    pns = ", ".join(part_numbers[:25])
    ask = (
        f"Search for end-of-life, discontinuation, last-time-buy, NRND or product change notices "
        f"from {maker} published in the last 12 months that affect any of these part numbers: {pns}. "
        "Prefer the maker's own PCN/EOL pages and distributor notices. List each notice you find "
        "with its part numbers, last order date, replacement and the URL. If you find none, say so."
    )
    messages = [{"role": "user", "content": ask}]
    resp = None
    for _ in range(4):  # resend paused server-tool turns
        resp = client.beta.messages.create(
            model=MODEL,
            max_tokens=8000,
            betas=[FALLBACK_BETA],
            fallbacks="default",
            output_config={"effort": "medium"},
            tools=[{"type": "web_search_20260209", "name": "web_search", "max_uses": max_searches}],
            messages=messages,
        )
        if resp.stop_reason != "pause_turn":
            break
        messages = [*messages, {"role": "assistant", "content": resp.content}]
    if resp is None or resp.stop_reason == "refusal":
        return []
    found = _text(resp)
    if not found.strip():
        return []
    data = _structured(
        client,
        "Turn this research summary into structured notices. Keep only notices that name at least "
        "one specific part number. Dates as YYYY-MM-DD or empty.",
        found,
        NEWS_SCHEMA,
    )
    return data.get("notices") or []
