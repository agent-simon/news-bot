# parsing.py
"""Tolerant JSON extraction from model responses. Shared by the web-search and
summary passes, both of which ask for raw JSON but occasionally get it fenced or
wrapped in prose."""
import json
import re


def extract_json(text):
    """Parse a JSON value out of a model response, tolerating a ```json fence or
    surrounding prose. Raises json.JSONDecodeError if nothing parseable is found."""
    raw = text.strip()
    # Strip a surrounding ```json ... ``` (or bare ```) code fence if present.
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    # The model sometimes wraps the array in prose ("Here are the items: [...]").
    # Fall back to slicing out the outermost JSON array/object.
    starts = [i for i in (raw.find("["), raw.find("{")) if i != -1]
    ends = [i for i in (raw.rfind("]"), raw.rfind("}")) if i != -1]
    if starts and ends:
        return json.loads(raw[min(starts):max(ends) + 1])
    raise json.JSONDecodeError("no JSON found", raw, 0)


def coerce_index(value):
    """Pull an integer item index out of the model's response. Tolerates ints,
    "0", and stray formatting like "[0]" (some models echo the label verbatim)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    match = re.search(r"\d+", str(value))
    return int(match.group()) if match else None
