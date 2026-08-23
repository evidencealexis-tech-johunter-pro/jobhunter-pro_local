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
from fastapi.testclient import TestClient
from jobs.service import background_tasks, get_job_state, update_job_state

sys.path.insert(
    0,
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
)

import main as app_module
from scraper import detect_and_fetch
app_module.detect_and_fetch = detect_and_fetch
app_module.background_tasks = background_tasks
app_module.get_job_state = get_job_state
app_module.update_job_state = update_job_state
from notifications.service import add_notification
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
    """Authenticate in an isolated browser session and return a Bearer token."""
    with TestClient(app_module.app) as auth_client:
        response = auth_client.post(
            "/api/apps/local/auth/login",
            json={
                "email": email,
                "password": TEST_PASSWORD,
            },
        )

        assert response.status_code == 200, response.text
        access_token = response.json()["access_token"]

    return {"Authorization": f"Bearer {access_token}"}
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
    primary_user_id = create_user("primary@example.com", "Primary")
    headers = login_as(client, "primary@example.com")

    job = create_job(
        client,
        headers,
        user_id="attacker-controlled-user-id",
    )

    assert job["user_id"] == primary_user_id

    conn = app_module.get_db()
    try:
        row = conn.execute(
            "SELECT data FROM Job WHERE id = ?",
            (job["id"],),
        ).fetchone()
        stored = json.loads(row["data"])
    finally:
        conn.close()

    assert stored["user_id"] == primary_user_id


def test_users_cannot_see_each_others_jobs(client, temp_db_path):
    create_user("primary@example.com", "Primary")
    create_user("secondary@example.com", "Secondary")

    primary_headers = login_as(client, "primary@example.com")
    secondary_headers = login_as(client, "secondary@example.com")

    primary_job = create_job(client, primary_headers, title="Primary Job")
    secondary_job = create_job(client, secondary_headers, title="Secondary Job")

    primary_jobs = client.get(
        "/api/apps/local/entities/Job",
        headers=primary_headers,
    )
    secondary_jobs = client.get(
        "/api/apps/local/entities/Job",
        headers=secondary_headers,
    )

    assert primary_jobs.status_code == 200
    assert secondary_jobs.status_code == 200

    assert [j["id"] for j in primary_jobs.json()] == [primary_job["id"]]
    assert [j["id"] for j in secondary_jobs.json()] == [secondary_job["id"]]


def test_users_cannot_update_each_others_jobs(client, temp_db_path):
    create_user("primary@example.com", "Primary")
    create_user("secondary@example.com", "Secondary")

    primary_headers = login_as(client, "primary@example.com")
    secondary_headers = login_as(client, "secondary@example.com")

    primary_job = create_job(client, primary_headers)

    response = client.patch(
        f"/api/apps/local/entities/Job/{primary_job['id']}",
        headers=secondary_headers,
        json={"title": "Secondary Took It"},
    )

    assert response.status_code == 404

    primary_jobs = client.get(
        "/api/apps/local/entities/Job",
        headers=primary_headers,
    )
    assert primary_jobs.status_code == 200
    assert primary_jobs.json()[0]["title"] == "Python Engineer"


def test_users_cannot_delete_each_others_jobs(client, temp_db_path):
    create_user("primary@example.com", "Primary")
    create_user("secondary@example.com", "Secondary")

    primary_headers = login_as(client, "primary@example.com")
    secondary_headers = login_as(client, "secondary@example.com")

    primary_job = create_job(client, primary_headers)

    response = client.delete(
        f"/api/apps/local/entities/Job/{primary_job['id']}",
        headers=secondary_headers,
    )

    assert response.status_code == 404

    primary_jobs = client.get(
        "/api/apps/local/entities/Job",
        headers=primary_headers,
    )
    assert primary_job["id"] in [j["id"] for j in primary_jobs.json()]


def test_clear_all_only_deletes_the_authenticated_users_jobs(
    client,
    temp_db_path,
):
    create_user("primary@example.com", "Primary")
    create_user("secondary@example.com", "Secondary")

    primary_headers = login_as(client, "primary@example.com")
    secondary_headers = login_as(client, "secondary@example.com")

    primary_job = create_job(client, primary_headers, title="Primary Job")
    secondary_job = create_job(client, secondary_headers, title="Secondary Job")

    response = client.delete(
        "/api/apps/local/entities/Job/clear-all",
        headers=primary_headers,
    )

    assert response.status_code == 200

    primary_jobs = client.get(
        "/api/apps/local/entities/Job",
        headers=primary_headers,
    )
    secondary_jobs = client.get(
        "/api/apps/local/entities/Job",
        headers=secondary_headers,
    )

    assert primary_jobs.status_code == 200
    assert secondary_jobs.status_code == 200
    assert primary_jobs.json() == []
    assert [j["id"] for j in secondary_jobs.json()] == [secondary_job["id"]]
    assert primary_job["id"] != secondary_job["id"]


@pytest.mark.asyncio
async def test_scrape_deduplication_is_scoped_to_the_authenticated_user(
    client,
    temp_db_path,
    monkeypatch,
):
    primary_user_id = create_user("primary@example.com", "Primary")
    secondary_user_id = create_user("secondary@example.com", "Secondary")

    primary_headers = login_as(client, "primary@example.com")
    secondary_headers = login_as(client, "secondary@example.com")

    # Each user needs an active resume for the scrape engine.
    for headers, skill in [
        (primary_headers, "PRIMARY_SKILL"),
        (secondary_headers, "SECONDARY_SKILL"),
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

    # Give Primary an existing job with the same dedup hash.
    shared_hash = "same-job-hash-for-two-users"
    primary_job = create_job(
        client,
        primary_headers,
        dedup_hash=shared_hash,
        title="Primary Existing Job",
    )

    # Secondary should still be able to save a job with Primary's same hash because
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
        headers=secondary_headers,
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

    assert captured_users == [secondary_user_id]

    secondary_jobs = client.get(
        "/api/apps/local/entities/Job",
        headers=secondary_headers,
    )

    assert secondary_jobs.status_code == 200
    secondary_job_ids = [j["id"] for j in secondary_jobs.json()]
    assert any(job_id != primary_job["id"] for job_id in secondary_job_ids)

    secondary_created = [
        j for j in secondary_jobs.json()
        if j["id"] != primary_job["id"]
    ]
    assert any(j.get("dedup_hash") == shared_hash for j in secondary_created)

    state = app_module.get_job_state(scrape_job_id, secondary_user_id)
    assert state is not None
    assert state["user_id"] == secondary_user_id


@pytest.mark.asyncio
async def test_user_cannot_read_or_stop_another_users_scrape_job(
    client,
    temp_db_path,
    monkeypatch,
):
    create_user("primary@example.com", "Primary")
    create_user("secondary@example.com", "Secondary")

    primary_headers = login_as(client, "primary@example.com")
    secondary_headers = login_as(client, "secondary@example.com")

    # Avoid requiring a real external scrape. Keep the task running long enough
    # for the ownership checks to happen.
    async def fake_run_scrape(job_id, req_data, user_id):
        app_module.update_job_state(job_id, stage="test-running")

    import jobs.router as jobs_router
    monkeypatch.setattr(jobs_router, "run_scrape", fake_run_scrape)

    response = client.post(
        "/api/apps/local/integration-endpoints/Core/ScrapeJobs",
        headers=primary_headers,
        json={
            "source_url": "https://example.com/jobs",
            "source_name": "Example",
        },
    )

    assert response.status_code == 200
    job_id = response.json()["job_id"]

    for task in list(app_module.background_tasks):
        await task

    secondary_status = client.get(
        f"/api/apps/local/integration-endpoints/Core/ScrapeJobs/{job_id}/status",
        headers=secondary_headers,
    )
    assert secondary_status.status_code == 404

    secondary_stop = client.post(
        f"/api/apps/local/integration-endpoints/Core/ScrapeJobs/{job_id}/stop",
        headers=secondary_headers,
    )
    assert secondary_stop.status_code == 404

    secondary_current = client.get(
        "/api/apps/local/integration-endpoints/Core/ScrapeJobs/current",
        headers=secondary_headers,
    )
    assert secondary_current.status_code == 200
    assert secondary_current.json()["job_id"] is None