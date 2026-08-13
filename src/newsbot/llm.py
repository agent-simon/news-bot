# llm.py
"""OpenAI client and model choices, constructed lazily so importing the news
modules (and testing pure helpers) doesn't require OPENAI_API_KEY."""
from functools import lru_cache

from openai import OpenAI

# Web search needs relevance judgment and source synthesis; summaries are a
# smaller, lower-cost task.
SEARCH_MODEL = "gpt-5.5"
SUMMARY_MODEL = "gpt-5.4-mini"


@lru_cache(maxsize=1)
def get_client():
    """The shared OpenAI client, built on first use and reused thereafter."""
    return OpenAI()


def response_text(response):
    """Return final text from a completed Responses API result, if available."""
    if getattr(response, "status", None) != "completed":
        return None

    final_text = []
    fallback_text = []
    for output in getattr(response, "output", []) or []:
        if getattr(output, "type", None) != "message":
            continue
        for content in getattr(output, "content", []) or []:
            if getattr(content, "type", None) == "refusal":
                continue
            if getattr(content, "type", None) != "output_text":
                continue
            text = getattr(content, "text", None)
            if not text:
                continue
            fallback_text.append(text)
            if getattr(output, "phase", None) == "final_answer":
                final_text.append(text)

    if final_text:
        return "\n".join(final_text)
    if fallback_text:
        return "\n".join(fallback_text)
    return getattr(response, "output_text", None) or None
