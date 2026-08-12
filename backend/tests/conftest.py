"""
Shared pytest fixtures. The most important thing this file does: it makes
every test run against a throwaway temporary SQLite file instead of your
real jobhunter_pro.db, so running the test suite can never corrupt or
delete real data.
"""
import os
import sys
import tempfile
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def temp_db_path(monkeypatch):
    """Point the app at a fresh, empty SQLite file for the duration of one test."""
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

    # Create tables the same way startup_event does
    conn = fake_get_db()
    for entity in ["Resume", "Job", "ScrapeSource", "ContextDocument", "AppSettings", "UserApiKey", "ScrapeJob", "Notification"]:
        conn.execute(f"CREATE TABLE IF NOT EXISTS {entity} (id TEXT PRIMARY KEY, data TEXT)")
    conn.commit()
    conn.close()

    yield path
    os.remove(path)


@pytest.fixture
def client(temp_db_path):
    """A FastAPI TestClient wired to the isolated temp database above."""
    from fastapi.testclient import TestClient
    import main as app_module
    return TestClient(app_module.app)