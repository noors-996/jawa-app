import json
import sqlite3
import threading
from datetime import datetime, timezone

from .config import DATA_DIR

_lock = threading.Lock()
_conn = sqlite3.connect(DATA_DIR / "app.db", check_same_thread=False)
_conn.row_factory = sqlite3.Row

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY, role TEXT, content TEXT, created TEXT);
CREATE TABLE IF NOT EXISTS posts (
  id INTEGER PRIMARY KEY, media_file TEXT, media_type TEXT, caption TEXT,
  scheduled_at TEXT, status TEXT, permalink TEXT, error TEXT, created TEXT);
CREATE TABLE IF NOT EXISTS actions (
  id INTEGER PRIMARY KEY, kind TEXT, payload TEXT, summary TEXT,
  status TEXT, result TEXT, created TEXT);
CREATE TABLE IF NOT EXISTS notes (id INTEGER PRIMARY KEY, text TEXT, link TEXT, seen INTEGER DEFAULT 0, created TEXT);
CREATE TABLE IF NOT EXISTS handled (item_id TEXT PRIMARY KEY, kind TEXT, at TEXT);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
"""

DEFAULT_SETTINGS = {
    "post_slots": ["10:30", "19:30"],   # Amman time
    "max_posts_per_day": 2,
    "autoreply_enabled": False,
    "autoreply_every_hours": 3,
    "autoreply_max_replies": 4,
    "autoreply_quiet_from": "00:30",
    "autoreply_quiet_to": "08:00",
    "paused": False,  # set automatically when Instagram blocks us; owner turns it off
}

with _lock:
    _conn.executescript(SCHEMA)
    _conn.commit()


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def q(sql, args=(), one=False):
    with _lock:
        cur = _conn.execute(sql, args)
        rows = [dict(r) for r in cur.fetchall()]
        _conn.commit()
    return (rows[0] if rows else None) if one else rows


def ins(sql, args=()):
    with _lock:
        cur = _conn.execute(sql, args)
        _conn.commit()
        return cur.lastrowid


# settings
def get_settings():
    s = dict(DEFAULT_SETTINGS)
    for r in q("SELECT key, value FROM settings"):
        s[r["key"]] = json.loads(r["value"])
    return s


def set_settings(values: dict):
    for k, v in values.items():
        if k in DEFAULT_SETTINGS:
            ins("INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (k, json.dumps(v, ensure_ascii=False)))
    return get_settings()


# notes for the owner
def add_note(text, link=""):
    return ins("INSERT INTO notes(text, link, created) VALUES(?,?,?)", (text, link, now_iso()))


# items already handled by auto-reply (never reply twice)
def is_handled(item_id):
    return q("SELECT 1 FROM handled WHERE item_id=?", (item_id,), one=True) is not None


def mark_handled(item_id, kind):
    ins("INSERT OR IGNORE INTO handled(item_id, kind, at) VALUES(?,?,?)", (item_id, kind, now_iso()))
