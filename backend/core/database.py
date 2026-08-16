from __future__ import annotations

import sqlite3

from .config import DATABASE_PATH, SQLITE_BUSY_TIMEOUT_MS


ENTITY_TABLES = (
    "Resume",
    "Job",
    "ScrapeSource",
    "ContextDocument",
    "AppSettings",
    "UserApiKey",
    "ScrapeJob",
    "Notification",
)


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}")
    return conn


def initialize_database(conn: sqlite3.Connection) -> None:
    for entity in ENTITY_TABLES:
        conn.execute(
            f"CREATE TABLE IF NOT EXISTS {entity} "
            "(id TEXT PRIMARY KEY, data TEXT)"
        )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            email TEXT NOT NULL UNIQUE,
            name TEXT,
            password_hash TEXT NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            last_login_at TEXT
        )
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS auth_sessions (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            token_hash TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            revoked_at TEXT,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
        """
    )

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_auth_sessions_token_hash
        ON auth_sessions(token_hash)
        """
    )

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_auth_sessions_user_id
        ON auth_sessions(user_id)
        """
    )


def mark_running_jobs_interrupted(conn: sqlite3.Connection) -> None:
    conn.execute(
        "UPDATE ScrapeJob SET data = json_set(data, '$.status', 'interrupted') "
        "WHERE json_extract(data, '$.status') = 'running'"
    )