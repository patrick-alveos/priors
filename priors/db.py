"""SQLite state store.

Tracks seen articles (cross-week dedup), sent issues, weekly prediction-market
snapshots (for week-over-week deltas), and subscribers.

The subscribers table is the Phase 4 seam: v1 seeds it with one row (the owner);
the future hosted newsletter is the same table with N rows and a signup page.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

DEFAULT_DB_PATH = Path("data/priors.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS articles (
    id            TEXT PRIMARY KEY,      -- stable hash of normalized URL
    url           TEXT NOT NULL,
    title         TEXT,
    source        TEXT,
    published_at  TEXT,
    first_seen_at TEXT NOT NULL,
    used_in_week  TEXT                   -- ISO week the article appeared in an issue
);

CREATE TABLE IF NOT EXISTS issues (
    week      TEXT PRIMARY KEY,          -- ISO year-week, e.g. '2026-W31'
    sent_at   TEXT,
    subject   TEXT,
    html_path TEXT,
    md_path   TEXT
);

CREATE TABLE IF NOT EXISTS market_snapshots (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    platform    TEXT NOT NULL,           -- polymarket | kalshi | metaculus
    market_id   TEXT NOT NULL,
    question    TEXT,
    probability REAL NOT NULL,           -- 0..1
    week        TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    UNIQUE (platform, market_id, week)
);

CREATE TABLE IF NOT EXISTS subscribers (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    email      TEXT NOT NULL UNIQUE,
    name       TEXT,
    status     TEXT NOT NULL DEFAULT 'active',   -- active | unsubscribed
    created_at TEXT NOT NULL
);
"""


def connect(path: Path | str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def seed_owner(conn: sqlite3.Connection, email: str, name: str) -> None:
    """Insert the owner as the first subscriber. Idempotent."""
    conn.execute(
        "INSERT OR IGNORE INTO subscribers (email, name, created_at) VALUES (?, ?, ?)",
        (email, name, datetime.now(UTC).isoformat()),
    )
    conn.commit()


def active_subscribers(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT email, name FROM subscribers WHERE status = 'active' ORDER BY id"
    ).fetchall()
