# dedup.py
import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

DB_FILE = "seen_links.db"
LEGACY_JSON_FILE = "seen_links.json"
RETENTION_DAYS = 14

# Query params that only track campaigns/clicks and never identify the article.
_TRACKING_PREFIXES = ("utm_",)
_TRACKING_KEYS = {"fbclid", "gclid", "mc_cid", "mc_eid"}


def normalize(link):
    """Canonicalize a URL for dedup: lowercase scheme/host, drop www., trailing
    slash, fragment, and tracking query params."""
    parts = urlsplit(link.strip())
    scheme = parts.scheme.lower()
    netloc = parts.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    path = parts.path.rstrip("/")
    query = urlencode([
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not k.lower().startswith(_TRACKING_PREFIXES) and k.lower() not in _TRACKING_KEYS
    ])
    return urlunsplit((scheme, netloc, path, query, ""))


def _connect():
    needs_migration = not os.path.exists(DB_FILE)
    conn = sqlite3.connect(DB_FILE)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS seen (link TEXT PRIMARY KEY, first_seen TEXT NOT NULL)"
    )
    if needs_migration:
        _migrate_legacy_json(conn)
    return conn


def _migrate_legacy_json(conn):
    """One-time import of the old seen_links.json so the cutover doesn't
    re-surface already-seen articles as new."""
    if not os.path.exists(LEGACY_JSON_FILE):
        return
    try:
        with open(LEGACY_JSON_FILE) as f:
            links = json.load(f)
    except (json.JSONDecodeError, OSError):
        return
    now = datetime.now(timezone.utc).isoformat()
    conn.executemany(
        "INSERT OR IGNORE INTO seen (link, first_seen) VALUES (?, ?)",
        [(normalize(link), now) for link in links],
    )
    conn.commit()


def _prune(conn):
    cutoff = (datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)).isoformat()
    conn.execute("DELETE FROM seen WHERE first_seen < ?", (cutoff,))
    conn.commit()


def load_seen():
    """Return the set of normalized links currently stored (post-prune)."""
    conn = _connect()
    try:
        _prune(conn)
        return {row[0] for row in conn.execute("SELECT link FROM seen")}
    finally:
        conn.close()


def mark_seen(links):
    """Persist links as seen (normalized, timestamped). Idempotent."""
    now = datetime.now(timezone.utc).isoformat()
    conn = _connect()
    try:
        conn.executemany(
            "INSERT OR IGNORE INTO seen (link, first_seen) VALUES (?, ?)",
            [(normalize(link), now) for link in links],
        )
        conn.commit()
        _prune(conn)
    finally:
        conn.close()
