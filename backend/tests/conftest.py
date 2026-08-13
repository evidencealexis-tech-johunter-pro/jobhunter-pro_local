"""
Shared pytest fixtures.

Every test runs against a temporary SQLite database rather than the real
jobhunter_pro.db, so the test suite cannot modify or delete real application
data.
"""

import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def temp_db_path(monkeypatch):
    """Create a fresh isolated SQLite database for one test."""

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    import main as app_module

    def fake_get_db():
        import sqlite3

        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    monkeypatch.setattr(app_module, "get_db", fake_get_db)

    conn = fake_get_db()

    # Existing application tables
    for entity in [
        "Resume",
        "Job",
        "ScrapeSource",
        "ContextDocument",
        "AppSettings",
        "UserApiKey",
        "ScrapeJob",
        "Notification",
    ]:
        conn.execute(
            f"CREATE TABLE IF NOT EXISTS {entity} "
            "(id TEXT PRIMARY KEY, data TEXT)"
        )

    # Authentication tables
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

    conn.commit()
    conn.close()

    yield path

    try:
        os.remove(path)
    except FileNotFoundError:
        pass


@pytest.fixture
def client(temp_db_path):
    """Return a FastAPI TestClient using the isolated test database."""

    from fastapi.testclient import TestClient
    import main as app_module

    return TestClient(app_module.app)