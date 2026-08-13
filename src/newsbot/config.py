# config.py
"""Runtime config: env-var flags and the feed/topic file.

Everything here is read on each call (not captured into module globals at import)
so tests can set os.environ and config edits take effect without a restart.
"""
import json
import os

from dotenv import load_dotenv

# Load .env once when config is first imported. Idempotent and harmless without a
# .env file; keeps env reads below working whether or not the entrypoint loaded it.
load_dotenv()

# Skip items older than this (days). Applied to both RSS and dated web results.
MAX_AGE_DAYS = 3

# How many search_themes /news samples per run (behaviour knob, not data).
THEMES_PER_RUN = 2

# Falsey spellings for the on/off env toggles.
_FALSEY = {"off", "false", "0", "no", "disabled"}


def _env_flag(name):
    """A toggle that is on by default (incl. unset/empty) and off only when set to
    a falsey spelling (off/false/0/no/disabled)."""
    return os.environ.get(name, "").strip().lower() not in _FALSEY


def web_search_enabled():
    """OpenAI web-search pass. Off selects RSS-only mode. Respected by both
    the daily job and /news."""
    return _env_flag("WEB_SEARCH")


def daily_news_enabled():
    """Scheduled 08:00 auto-post. Off leaves the /news command available."""
    return _env_flag("DAILY_NEWS")


def config_path():
    """Path to the feed/topic config: SOURCES_PATH if set, else the module-relative
    sources.json (CWD-independent). SOURCES_PATH lets the Pi read an untracked
    sources.local.json edited in place without a commit/PR/deploy."""
    return os.environ.get("SOURCES_PATH", "").strip() or os.path.join(
        os.path.dirname(__file__), "sources.json"
    )


def load_config():
    """Read the feed/topic config fresh, so edits apply without a restart.

      "sources"            — RSS/Atom feeds: {url, limit, name}
      "known_source_names" — display labels for web-search hosts (netloc sans www.)
      "base_topics"        — fixed topics every web search covers
      "search_themes"      — extra topics /news mixes in at random
    """
    with open(config_path(), encoding="utf-8") as f:
        return json.load(f)
