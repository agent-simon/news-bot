# llm.py
"""Anthropic client + model choices, constructed lazily so importing the news
modules (and testing the pure helpers) doesn't require ANTHROPIC_API_KEY."""
from functools import lru_cache

from anthropic import Anthropic

# Web search needs relevance judgement + synthesis, so it stays on Sonnet.
# Summarising titles into emoji + a one-liner is simple, so Haiku does it
# (~3x cheaper per token and faster).
SEARCH_MODEL = "claude-sonnet-4-6"
SUMMARY_MODEL = "claude-haiku-4-5"


@lru_cache(maxsize=1)
def get_client():
    """The shared Anthropic client, built on first use and reused thereafter."""
    return Anthropic()
