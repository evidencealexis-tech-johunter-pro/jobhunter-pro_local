"""
Regression test for a real bug found during testing: the generic
DELETE /{entity_name}/{item_id} route was registered BEFORE the specific
DELETE /Job/clear-all route, so FastAPI matched "clear-all" as if it were
an item_id and silently deleted nothing - while still returning 200 OK,
making it look like it worked when it didn't.

This test creates real Job rows, calls the clear-all endpoint, and checks
the database directly - not just the HTTP status code - so it can never
pass while silently doing nothing again.
"""
import json
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_clear_all_actually_deletes_every_job(client, temp_db_path):
    import sqlite3

    # Seed 3 fake jobs directly into the test database
    conn = sqlite3.connect(temp_db_path)
    for i in range(3):
        conn.execute(
            "INSERT INTO Job (id, data) VALUES (?, ?)",
            (f"job-{i}", json.dumps({"id": f"job-{i}", "title": f"Test Job {i}"})),
        )
    conn.commit()

    # Sanity check: the jobs are really there before we clear anything
    count_before = conn.execute("SELECT COUNT(*) FROM Job").fetchone()[0]
    assert count_before == 3
    conn.close()

    # Call the actual endpoint the frontend's "Clear All Jobs" button hits
    response = client.delete("/api/apps/local/entities/Job/clear-all")
    assert response.status_code == 200
    assert response.json()["status"] == "success"

    # THE REAL CHECK: verify the database, not just the HTTP response.
    # A 200 OK alone is exactly what fooled everyone during the original bug.
    conn = sqlite3.connect(temp_db_path)
    count_after = conn.execute("SELECT COUNT(*) FROM Job").fetchone()[0]
    conn.close()
    assert count_after == 0, (
        "Clear All returned success but jobs still exist - this is the "
        "exact route-ordering regression that happened before."
    )


def test_deleting_a_single_job_by_id_still_works(client, temp_db_path):
    """Make sure fixing the clear-all route didn't break normal single-item
    deletes, which go through the generic /{entity_name}/{item_id} route."""
    import sqlite3

    conn = sqlite3.connect(temp_db_path)
    conn.execute("INSERT INTO Job (id, data) VALUES (?, ?)", ("job-x", json.dumps({"id": "job-x"})))
    conn.execute("INSERT INTO Job (id, data) VALUES (?, ?)", ("job-y", json.dumps({"id": "job-y"})))
    conn.commit()
    conn.close()

    response = client.delete("/api/apps/local/entities/Job/job-x")
    assert response.status_code == 200

    conn = sqlite3.connect(temp_db_path)
    remaining_ids = [row[0] for row in conn.execute("SELECT id FROM Job").fetchall()]
    conn.close()
    assert remaining_ids == ["job-y"]