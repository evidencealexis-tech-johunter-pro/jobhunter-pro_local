"""
Job and scrape-job ownership tests.

These tests prove that jobs belong to the authenticated user, that one user
cannot read/mutate another user's jobs, and that scrape-job state is similarly
owner-scoped.
"""

import json
import os
import sys
import uuid
from datetime import datetime, timezone

import pytest

sys.path.insert(
    0,
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
)

import main as app_module
from auth import hash_password


TEST_PASSWORD = "CorrectHorseBatteryStaple!"


def create_user(email: str, name: str):
    conn = app_module.get_db()
    user_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    conn.execute(
        """
        INSERT INTO users (
            id, email, name, password_hash, is_active,
            created_at, updated_at, last_login_at
        )
        VALUES (?, ?, ?, ?, 1, ?, ?, NULL)
        """,
        (
            user_id,
            email,
            name,
            hash_password(TEST_PASSWORD),
            now,
            now,
        ),
    )
    conn.commit()
    conn.close()
    return user_id


def login_as(client, email: str):
    response = client.post(
        "/api/apps/local/auth/login",
        json={"email": email, "password": TEST_PASSWORD},
    )
    assert response.status_code == 200
    return {
        "Authorization": f"Bearer {response.json()['access_token']}"
    }


def create_job(client, headers, **overrides):
    payload = {
        "title": "Python Engineer",
        "company": "Example Co",
        "description": "Build backend systems.",
        "dedup_hash": str(uuid.uuid4()),
        "status": "new",
        "dismissed": False,
        **overrides,
    }
    response = client.post(
        "/api/apps/local/entities/Job",
        headers=headers,
        json=payload,
    )
    assert response.status_code == 200
    return response.json()


def test_jobs_require_authentication(client, temp_db_path):
    response = client.get("/api/apps/local/entities/Job")
    assert response.status_code == 401


def test_job_creation_uses_authenticated_user_and_ignores_client_user_id(
    client,
    temp_db_path,
):
    alice_id = create_user("alice@example.com", "Alice")
    headers = login_as(client, "alice@example.com")

    job = create_job(
        client,
        headers,
        user_id="attacker-controlled-user-id",
    )

    assert job["user_id"] == alice_id

    conn = app_module.get_db()
    try:
        row = conn.execute(
            "SELECT data FROM Job WHERE id = ?",
            (job["id"],),
        ).fetchone()
        stored = json.loads(row["data"])
    finally:
        conn.close()

    assert stored["user_id"] == alice_id


def test_users_cannot_see_each_others_jobs(client, temp_db_path):
    create_user("alice@example.com", "Alice")
    create_user("bob@example.com", "Bob")

    alice_headers = login_as(client, "alice@example.com")
    bob_headers = login_as(client, "bob@example.com")

    alice_job = create_job(client, alice_headers, title="Alice Job")
    bob_job = create_job(client, bob_headers, title="Bob Job")

    alice_jobs = client.get(
        "/api/apps/local/entities/Job",
        headers=alice_headers,
    )
    bob_jobs = client.get(
        "/api/apps/local/entities/Job",
        headers=bob_headers,
    )

    assert alice_jobs.status_code == 200
    assert bob_jobs.status_code == 200

    assert [j["id"] for j in alice_jobs.json()] == [alice_job["id"]]
    assert [j["id"] for j in bob_jobs.json()] == [bob_job["id"]]


def test_users_cannot_update_each_others_jobs(client, temp_db_path):
    create_user("alice@example.com", "Alice")
    create_user("bob@example.com", "Bob")

    alice_headers = login_as(client, "alice@example.com")
    bob_headers = login_as(client, "bob@example.com")

    alice_job = create_job(client, alice_headers)

    response = client.patch(
        f"/api/apps/local/entities/Job/{alice_job['id']}",
        headers=bob_headers,
        json={"title": "Bob Took It"},
    )

    assert response.status_code == 404

    alice_jobs = client.get(
        "/api/apps/local/entities/Job",
        headers=alice_headers,
    )
    assert alice_jobs.status_code == 200
    assert alice_jobs.json()[0]["title"] == "Python Engineer"


def test_users_cannot_delete_each_others_jobs(client, temp_db_path):
    create_user("alice@example.com", "Alice")
    create_user("bob@example.com", "Bob")

    alice_headers = login_as(client, "alice@example.com")
    bob_headers = login_as(client, "bob@example.com")

    alice_job = create_job(client, alice_headers)

    response = client.delete(
        f"/api/apps/local/entities/Job/{alice_job['id']}",
        headers=bob_headers,
    )

    assert response.status_code == 404

    alice_jobs = client.get(
        "/api/apps/local/entities/Job",
        headers=alice_headers,
    )
    assert alice_job["id"] in [j["id"] for j in alice_jobs.json()]


def test_clear_all_only_deletes_the_authenticated_users_jobs(
    client,
    temp_db_path,
):
    create_user("alice@example.com", "Alice")
    create_user("bob@example.com", "Bob")

    alice_headers = login_as(client, "alice@example.com")
    bob_headers = login_as(client, "bob@example.com")

    alice_job = create_job(client, alice_headers, title="Alice Job")
    bob_job = create_job(client, bob_headers, title="Bob Job")

    response = client.delete(
        "/api/apps/local/entities/Job/clear-all",
        headers=alice_headers,
    )

    assert response.status_code == 200

    alice_jobs = client.get(
        "/api/apps/local/entities/Job",
        headers=alice_headers,
    )
    bob_jobs = client.get(
        "/api/apps/local/entities/Job",
        headers=bob_headers,
    )

    assert alice_jobs.status_code == 200
    assert bob_jobs.status_code == 200
    assert alice_jobs.json() == []
    assert [j["id"] for j in bob_jobs.json()] == [bob_job["id"]]
    assert alice_job["id"] != bob_job["id"]


@pytest.mark.asyncio
async def test_scrape_deduplication_is_scoped_to_the_authenticated_user(
    client,
    temp_db_path,
    monkeypatch,
):
    alice_id = create_user("alice@example.com", "Alice")
    bob_id = create_user("bob@example.com", "Bob")

    alice_headers = login_as(client, "alice@example.com")
    bob_headers = login_as(client, "bob@example.com")

    # Each user needs an active resume for the scrape engine.
    for headers, skill in [
        (alice_headers, "ALICE_SKILL"),
        (bob_headers, "BOB_SKILL"),
    ]:
        response = client.post(
            "/api/apps/local/entities/Resume",
            headers=headers,
            json={
                "name": "Resume",
                "skills": [skill],
                "active": True,
                "seniority": "Senior",
                "years_exp": 5,
            },
        )
        assert response.status_code == 200

    # Give Alice an existing job with the same dedup hash.
    shared_hash = "same-job-hash-for-two-users"
    alice_job = create_job(
        client,
        alice_headers,
        dedup_hash=shared_hash,
        title="Alice Existing Job",
    )

    # Bob should still be able to save a job with Alice's same hash because
    # deduplication is an ownership concern, not a global application concern.
    captured_users = []

    async def fake_llm(**kwargs):
        captured_users.append(kwargs.get("user_id"))
        return {
            "skills_score": 100,
            "semantic_score": 100,
            "seniority_score": 100,
            "domain_score": 100,
            "legitimacy_score": 100,
            "match_reasons": [],
            "skill_gaps": [],
            "red_flags": [],
        }

    def fake_detect_and_fetch(source_url):
        return (
            "structured",
            [
                {
                    "title": "Shared Hash Job",
                    "company": "Example Co",
                    "location": "Remote",
                    "url": "https://example.com/job/1",
                    "description": "Python backend engineering role",
                    "dedup_hash": shared_hash,
                }
            ],
        )

    monkeypatch.setattr(
        app_module,
        "call_llm_with_retry_async",
        fake_llm,
    )
    monkeypatch.setattr(
        app_module,
        "detect_and_fetch",
        fake_detect_and_fetch,
    )

    response = client.post(
        "/api/apps/local/integration-endpoints/Core/ScrapeJobs",
        headers=bob_headers,
        json={
            "source_url": "https://example.com/jobs",
            "source_name": "Example",
            "match_threshold": 70,
        },
    )

    assert response.status_code == 200
    scrape_job_id = response.json()["job_id"]

    for task in list(app_module.background_tasks):
        await task

    assert captured_users == [bob_id]

    bob_jobs = client.get(
        "/api/apps/local/entities/Job",
        headers=bob_headers,
    )

    assert bob_jobs.status_code == 200
    bob_job_ids = [j["id"] for j in bob_jobs.json()]
    assert any(job_id != alice_job["id"] for job_id in bob_job_ids)

    bob_created = [
        j for j in bob_jobs.json()
        if j["id"] != alice_job["id"]
    ]
    assert any(j.get("dedup_hash") == shared_hash for j in bob_created)

    state = app_module.get_job_state(scrape_job_id, bob_id)
    assert state is not None
    assert state["user_id"] == bob_id


@pytest.mark.asyncio
async def test_user_cannot_read_or_stop_another_users_scrape_job(
    client,
    temp_db_path,
    monkeypatch,
):
    create_user("alice@example.com", "Alice")
    create_user("bob@example.com", "Bob")

    alice_headers = login_as(client, "alice@example.com")
    bob_headers = login_as(client, "bob@example.com")

    # Avoid requiring a real external scrape. Keep the task running long enough
    # for the ownership checks to happen.
    async def fake_run_scrape(job_id, req_data, user_id):
        app_module.update_job_state(job_id, stage="test-running")

    monkeypatch.setattr(app_module, "run_scrape", fake_run_scrape)

    response = client.post(
        "/api/apps/local/integration-endpoints/Core/ScrapeJobs",
        headers=alice_headers,
        json={
            "source_url": "https://example.com/jobs",
            "source_name": "Example",
        },
    )

    assert response.status_code == 200
    job_id = response.json()["job_id"]

    for task in list(app_module.background_tasks):
        await task

    bob_status = client.get(
        f"/api/apps/local/integration-endpoints/Core/ScrapeJobs/{job_id}/status",
        headers=bob_headers,
    )
    assert bob_status.status_code == 404

    bob_stop = client.post(
        f"/api/apps/local/integration-endpoints/Core/ScrapeJobs/{job_id}/stop",
        headers=bob_headers,
    )
    assert bob_stop.status_code == 404

    bob_current = client.get(
        "/api/apps/local/integration-endpoints/Core/ScrapeJobs/current",
        headers=bob_headers,
    )
    assert bob_current.status_code == 200
    assert bob_current.json()["job_id"] is None