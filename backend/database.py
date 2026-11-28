# backend/database.py
"""SQLite storage for Momo (data/memory.db).

Tables
    sessions, messages           conversation history (one row per message; `tools` = what Momo did that turn)
    user_facts                   long-term memory about the user
    tracks, playlists,
    playlist_tracks, play_history   music library
    reminders                    timers, alarms and reminders (Phase 2)
    list_items                   to-do / shopping / any named list (Phase 2)
    events                       calendar events you added by voice (Google Calendar is read live, not stored)
    news_domains                 the news domains you follow (Momo fetches these by herself)
    news_items                   headlines cached for your news domains (Phase 3, already sanitised)
    email_outbox                 email drafts waiting for / given approval in the window (Phase 3)
    security_events              audit log: blocked egress, dropped injections, approvals (Phase 3)
(Old `mood_state` / `mood_events` tables from the removed mood system are left untouched.)

Old layouts are migrated automatically on startup.
"""
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone

DB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
DB_PATH = os.getenv("MOMO_DB") or os.path.join(DB_DIR, "memory.db")      # MOMO_DB: tests use a copy

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id  TEXT PRIMARY KEY,
    started_at  TEXT NOT NULL,
    ended_at    TEXT,
    title       TEXT
);
CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    role        TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    content     TEXT NOT NULL,
    model       TEXT,
    latency_ms  INTEGER,
    emotion     TEXT,
    tools       TEXT,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, id);

CREATE TABLE IF NOT EXISTS user_facts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    fact        TEXT NOT NULL UNIQUE,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tracks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id    TEXT NOT NULL UNIQUE,
    title       TEXT,
    duration    INTEGER,
    query       TEXT,
    added_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS playlists (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE COLLATE NOCASE,
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS playlist_tracks (
    playlist_id INTEGER NOT NULL REFERENCES playlists(id) ON DELETE CASCADE,
    track_id    INTEGER NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
    position    INTEGER NOT NULL,
    PRIMARY KEY (playlist_id, track_id)
);
CREATE TABLE IF NOT EXISTS play_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    track_id    INTEGER NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
    source      TEXT,
    played_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reminders (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    kind        TEXT NOT NULL CHECK (kind IN ('timer', 'alarm', 'reminder')),
    label       TEXT,
    due_at      TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'done', 'cancelled'))
);
CREATE INDEX IF NOT EXISTS idx_reminders_due ON reminders(status, due_at);

CREATE TABLE IF NOT EXISTS list_items (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    list_name   TEXT NOT NULL COLLATE NOCASE,
    item        TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    UNIQUE (list_name, item)
);

CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT NOT NULL,
    start_at    TEXT NOT NULL,
    all_day     INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'cancelled'))
);
CREATE TABLE IF NOT EXISTS news_domains (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE COLLATE NOCASE,
    added_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS news_items (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    topic       TEXT NOT NULL COLLATE NOCASE,
    title       TEXT NOT NULL,
    source      TEXT,
    published   TEXT,
    fetched_at  TEXT NOT NULL,
    UNIQUE (topic, title)
);
CREATE TABLE IF NOT EXISTS email_outbox (
    id          TEXT PRIMARY KEY,
    to_name     TEXT NOT NULL,
    to_addr     TEXT NOT NULL,
    subject     TEXT NOT NULL,
    body        TEXT NOT NULL,
    tainted     INTEGER NOT NULL DEFAULT 0,
    status      TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'sent', 'rejected', 'expired', 'failed')),
    created_at  TEXT NOT NULL,
    decided_at  TEXT,
    note        TEXT
);
CREATE TABLE IF NOT EXISTS security_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    kind        TEXT NOT NULL,
    detail      TEXT,
    created_at  TEXT NOT NULL
);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _migrate(conn: sqlite3.Connection) -> None:
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    # v1 -> v2: `conversations` (user/ai pairs) -> `messages`
    if "conversations" in tables:
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(sessions)")}
        if "start_time" in cols:
            conn.execute("ALTER TABLE sessions RENAME COLUMN start_time TO started_at")
            conn.execute("ALTER TABLE sessions ADD COLUMN ended_at TEXT")
            conn.execute("ALTER TABLE sessions ADD COLUMN title TEXT")
        conn.executescript(SCHEMA)
        for row in conn.execute("SELECT * FROM conversations ORDER BY id").fetchall():
            for role, text in (("user", row["user_message"]), ("assistant", row["ai_response"])):
                conn.execute("INSERT INTO messages (session_id, role, content, created_at) VALUES (?, ?, ?, ?)",
                             (row["session_id"], role, text, row["timestamp"]))
        conn.execute("DROP TABLE conversations")
    # v2 -> v3: emotion column on messages
    if "messages" in tables:
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(messages)")}
        if "emotion" not in cols:
            conn.execute("ALTER TABLE messages ADD COLUMN emotion TEXT")
        # v3 -> v4: what Momo did in each turn (tool calls + locally built results), for context memory
        if "tools" not in cols:
            conn.execute("ALTER TABLE messages ADD COLUMN tools TEXT")


def setup_database() -> None:
    os.makedirs(DB_DIR, exist_ok=True)
    with connect() as conn:
        _migrate(conn)
        fresh = not conn.execute("SELECT 1 FROM sqlite_master WHERE name='news_domains'").fetchone()
        conn.executescript(SCHEMA)
        if fresh:                                      # first run: your starting list (edit it any time)
            conn.executemany("INSERT OR IGNORE INTO news_domains (name, added_at) VALUES (?, ?)",
                             [(d, now()) for d in DEFAULT_NEWS_DOMAINS])


# --- news domains (what Momo follows) ---
DEFAULT_NEWS_DOMAINS = ["AI", "gaming", "tech", "anime and pop culture", "Marvel"]


def news_domains() -> list[str]:
    with connect() as conn:
        return [r["name"] for r in conn.execute("SELECT name FROM news_domains ORDER BY id")]


def add_news_domain(name: str) -> bool:
    with connect() as conn:
        return conn.execute("INSERT OR IGNORE INTO news_domains (name, added_at) VALUES (?, ?)",
                            (name.strip(), now())).rowcount > 0


def remove_news_domain(name: str) -> bool:
    with connect() as conn:
        return conn.execute("DELETE FROM news_domains WHERE name = ?", (name.strip(),)).rowcount > 0


# --- sessions & messages ---
def initialize_session() -> str:
    session_id = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    with connect() as conn:
        conn.execute("INSERT INTO sessions (session_id, started_at) VALUES (?, ?)", (session_id, now()))
    return session_id


def end_session(session_id: str) -> None:
    with connect() as conn:
        conn.execute("UPDATE sessions SET ended_at = ? WHERE session_id = ?", (now(), session_id))


def add_message(session_id, role, content, model=None, latency_ms=None, tools=None) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO messages (session_id, role, content, model, latency_ms, tools, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)", (session_id, role, content, model, latency_ms, tools, now()))


def last_assistant_message(session_id: str):
    with connect() as conn:
        r = conn.execute("SELECT content, tools FROM messages WHERE session_id = ? AND role = 'assistant' "
                         "ORDER BY id DESC LIMIT 1", (session_id,)).fetchone()
    return dict(r) if r else None


def get_recent_messages(session_id: str, limit: int = 10) -> list[dict]:
    """Last `limit` messages of a session, oldest first."""
    with connect() as conn:
        rows = conn.execute("SELECT role, content, tools FROM messages WHERE session_id = ? ORDER BY id DESC LIMIT ?",
                            (session_id, limit)).fetchall()
    return [dict(r) for r in reversed(rows)]


# --- long-term memory ---
def add_fact(fact: str) -> None:
    with connect() as conn:
        conn.execute("INSERT OR IGNORE INTO user_facts (fact, created_at) VALUES (?, ?)", (fact.strip(), now()))


def remove_fact(text: str) -> int:
    with connect() as conn:
        return conn.execute("DELETE FROM user_facts WHERE fact LIKE ?", (f"%{text.strip()}%",)).rowcount


def get_facts(limit: int = 30) -> list[str]:
    with connect() as conn:
        return [r["fact"] for r in conn.execute("SELECT fact FROM user_facts ORDER BY id DESC LIMIT ?", (limit,))]


setup_database()
