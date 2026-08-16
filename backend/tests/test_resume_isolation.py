"""
Resume ownership and isolation tests.

These prove that resume data is bound to the authenticated user and that
the scrape engine can only select the active resume belonging to that user.
"""

import os
import sys
import uuid
import json
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

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
            id,
            email,
            name,
            password_hash,
            is_active,
            created_at,
            updated_at,
            last_login_at
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
def create_resume(client, headers, **overrides):
    payload = {
        "file_name": "resume.pdf",
        "name": "My Resume",
        "summary": "Test resume",
        "skills": ["Python", "FastAPI"],
        "seniority": "Senior",
        "years_experience": 8,
        "years_exp": 8,
        "active": True,
        **overrides,
    }

    response = client.post(
        "/api/apps/local/entities/Resume",
        headers=headers,
        json=payload,
    )

    assert response.status_code == 200

    return response.json()


def test_resume_requires_authentication(client, temp_db_path):
    response = client.get(
        "/api/apps/local/entities/Resume"
    )

    assert response.status_code == 401


def test_resume_creation_binds_server_side_user_id(
    client,
    temp_db_path,
):
    create_user(
        "primary@example.com",
        "Primary",
    )

    headers = login_as(
        client,
        "primary@example.com",
    )

    resume = create_resume(
        client,
        headers,
        user_id="attacker-supplied-user-id",
    )

    assert resume["user_id"] != "attacker-supplied-user-id"

    conn = app_module.get_db()

    try:
        row = conn.execute(
            "SELECT data FROM Resume WHERE id = ?",
            (resume["id"],),
        ).fetchone()

        stored = json.loads(row["data"])

    finally:
        conn.close()

    assert stored["user_id"] == resume["user_id"]


def test_users_cannot_see_each_others_resumes(
    client,
    temp_db_path,
):
    primary_user_id = create_user(
        "primary@example.com",
        "Primary",
    )

    create_user(
        "secondary@example.com",
        "Secondary",
    )

    primary_headers = login_as(
        client,
        "primary@example.com",
    )

    secondary_headers = login_as(
        client,
        "secondary@example.com",
    )

    resume = create_resume(
        client,
        primary_headers,
        file_name="primary.pdf",
    )

    primary_resumes = client.get(
        "/api/apps/local/entities/Resume",
        headers=primary_headers,
    )

    assert primary_resumes.status_code == 200
    assert [r["id"] for r in primary_resumes.json()] == [resume["id"]]

    secondary_resumes = client.get(
        "/api/apps/local/entities/Resume",
        headers=secondary_headers,
    )

    assert secondary_resumes.status_code == 200
    assert resume["id"] not in [
        r["id"] for r in secondary_resumes.json()
    ]

    assert primary_user_id == resume["user_id"]


def test_users_cannot_update_each_others_resumes(
    client,
    temp_db_path,
):
    create_user(
        "primary@example.com",
        "Primary",
    )

    create_user(
        "secondary@example.com",
        "Secondary",
    )

    primary_headers = login_as(
        client,
        "primary@example.com",
    )

    secondary_headers = login_as(
        client,
        "secondary@example.com",
    )

    resume = create_resume(
        client,
        primary_headers,
    )

    response = client.patch(
        f"/api/apps/local/entities/Resume/{resume['id']}",
        headers=secondary_headers,
        json={
            "summary": "Secondary should not be able to change this.",
        },
    )

    assert response.status_code == 404


def test_users_cannot_delete_each_others_resumes(
    client,
    temp_db_path,
):
    create_user(
        "primary@example.com",
        "Primary",
    )

    create_user(
        "secondary@example.com",
        "Secondary",
    )

    primary_headers = login_as(
        client,
        "primary@example.com",
    )

    secondary_headers = login_as(
        client,
        "secondary@example.com",
    )

    resume = create_resume(
        client,
        primary_headers,
    )

    response = client.delete(
        f"/api/apps/local/entities/Resume/{resume['id']}",
        headers=secondary_headers,
    )

    assert response.status_code == 404

    primary_view = client.get(
        "/api/apps/local/entities/Resume",
        headers=primary_headers,
    )

    assert primary_view.status_code == 200
    assert resume["id"] in [
        r["id"] for r in primary_view.json()
    ]


@pytest.mark.asyncio
async def test_scrape_uses_only_the_authenticated_users_active_resume(
    client,
    temp_db_path,
    monkeypatch,
):
    primary_user_id = create_user(
        "primary@example.com",
        "Primary",
    )

    create_user(
        "secondary@example.com",
        "Secondary",
    )

    primary_headers = login_as(
        client,
        "primary@example.com",
    )

    secondary_headers = login_as(
        client,
        "secondary@example.com",
    )

    create_resume(
        client,
        primary_headers,
        file_name="primary.pdf",
        skills=["PRIMARY_ONLY_SKILL"],
        seniority="Primary Senior",
        years_exp=11,
    )

    create_resume(
        client,
        secondary_headers,
        file_name="secondary.pdf",
        skills=["SECONDARY_ONLY_SKILL"],
        seniority="Secondary Senior",
        years_exp=22,
    )

    captured_prompts = []

    async def fake_call_llm_with_retry_async(
        system_prompt="",
        user_prompt="",
        max_retries=3,
        model=None,
        user_id=None,
    ):
        captured_prompts.append(
            {
                "user_id": user_id,
                "prompt": user_prompt,
            }
        )

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
                    "title": "Python Engineer",
                    "company": "Example Co",
                    "location": "Remote",
                    "url": "https://example.com/job/1",
                    "description": "Python FastAPI engineer",
                    "dedup_hash": "resume-isolation-test-job",
                }
            ],
        )

    monkeypatch.setattr(
        app_module,
        "call_llm_with_retry_async",
        fake_call_llm_with_retry_async,
    )

    monkeypatch.setattr(
        app_module,
        "detect_and_fetch",
        fake_detect_and_fetch,
    )

    scrape_response = client.post(
        "/api/apps/local/integration-endpoints/Core/ScrapeJobs",
        headers=primary_headers,
        json={
            "source_url": "https://example.com/jobs",
            "source_name": "Example",
            "match_threshold": 70,
        },
    )

    assert scrape_response.status_code == 200

    job_id = scrape_response.json()["job_id"]

    # Let the created background task run to completion.
    for task in list(app_module.background_tasks):
        await task

    assert captured_prompts

    primary_prompt = captured_prompts[0]["prompt"]

    assert captured_prompts[0]["user_id"] == primary_user_id
    assert "primary_only_skill" in primary_prompt
    assert "Primary Senior" in primary_prompt
    assert "secondary_only_skill" not in primary_prompt
    assert "Secondary Senior" not in primary_prompt

    state = app_module.get_job_state(job_id)

    assert state is not None
    assert state["user_id"] == primary_user_id