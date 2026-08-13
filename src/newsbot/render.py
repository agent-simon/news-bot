# render.py
"""Turn collected items into the rendered Telegram message. summarize() asks the
model only for an emoji + 1-2 sentence summary keyed by index; titles, links and
sources stay local, which keeps output small and the URLs un-mangled."""
import html
import json
import logging

from .llm import SUMMARY_MODEL, get_client, response_text
from .parsing import coerce_index, extract_json

logger = logging.getLogger(__name__)


def _render(items, enrichments):
    """Build the HTML Telegram message as a list of entries, each
    {text, links}. The leading title entry has no links; every item entry
    carries its own link so the sender can mark items seen per delivered chunk.
    `enrichments` maps an item index to {emoji, summary}; missing entries fall
    back to the item's own data."""
    entries = [{"text": f"📰 <b>{len(items)} new item(s)</b>", "links": []}]
    for idx, item in enumerate(items):
        enr = enrichments.get(idx, {})
        emoji = enr.get("emoji") or "🔹"
        summary = html.escape(enr.get("summary") or item["summary"] or "")
        title = html.escape(item["title"])
        link = item["link"]
        source = html.escape(item.get("source", ""))
        if link:
            header = f'{emoji} <a href="{html.escape(link, quote=True)}"><b>{title}</b></a>'
        else:
            header = f"{emoji} <b>{title}</b>"
        if source:
            header += f" <i>({source})</i>"
        text = f"{header}\n{summary}" if summary else header
        entries.append({"text": text, "links": [link] if link else []})

    return entries


def summarize(items):
    """Return the rendered message as a list of {text, links} entries (see
    _render). An empty-news run returns a single linkless notice entry."""
    if not items:
        return [{"text": "📰 No new relevant items today.", "links": []}]

    # Ask only for emoji + summary keyed by index; title/link/source stay local.
    # This keeps output small (avoids token-limit truncation) and removes the
    # risk of the model mangling copied URLs.
    text_blob = "\n\n".join(
        f"Item {idx}:\nTitle: {i['title']}\nRaw: {i['summary'][:300]}"
        for idx, i in enumerate(items)
    )
    response = get_client().responses.create(
        model=SUMMARY_MODEL,
        reasoning={"effort": "none"},
        max_output_tokens=4000,
        store=False,
        input=[{
            "role": "user",
            "content": (
                "For each item below, write a 1-2 sentence summary based on the title "
                "(the raw content may be sparse) and pick one emoji that fits its topic. "
                "Include ALL items, even if the raw content is empty — infer from the title.\n\n"
                "Respond with ONLY a JSON object containing an \"items\" array. Each "
                "item must be {\"i\": <integer>, \"emoji\": <string>, \"summary\": <string>}.\n\n"
                f"{text_blob}"
            )
        }],
        text={
            "format": {
                "type": "json_schema",
                "name": "news_summaries",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "items": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "i": {"type": "integer", "minimum": 0},
                                    "emoji": {"type": "string"},
                                    "summary": {"type": "string"},
                                },
                                "required": ["i", "emoji", "summary"],
                                "additionalProperties": False,
                            },
                        }
                    },
                    "required": ["items"],
                    "additionalProperties": False,
                },
            }
        },
    )

    text = response_text(response)
    if not text:
        logger.warning("summarize: response had no usable output; using raw items")
        return _render(items, {})
    try:
        payload = extract_json(text)
    except json.JSONDecodeError:
        # Never leak raw model output to Telegram — render from local items.
        logger.warning("summarize: could not parse response as JSON; using raw items")
        return _render(items, {})

    results = payload.get("items", []) if isinstance(payload, dict) else payload
    if not isinstance(results, list):
        return _render(items, {})
    enrichments = {}
    for r in results:
        if not isinstance(r, dict):
            continue
        idx = coerce_index(r.get("i"))
        if idx is not None and 0 <= idx < len(items):
            emoji = r.get("emoji")
            summary = r.get("summary")
            enrichments[idx] = {
                "emoji": emoji if isinstance(emoji, str) else None,
                "summary": summary if isinstance(summary, str) else None,
            }

    return _render(items, enrichments)
