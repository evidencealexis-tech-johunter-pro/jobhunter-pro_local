import os
import sys
import uuid
from datetime import datetime, timezone

sys.path.insert(
    0,
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
)

import main as app_module
from auth import hash_password


TEST_PASSWORD = "CorrectHorseBatteryStaple!"


def create_user(email="test@example.com", name="Test User"):
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


def login_as(client, email="test@example.com"):
    response = client.post(
        "/api/apps/local/auth/login",
        json={
            "email": email,
            "password": TEST_PASSWORD,
        },
    )

    assert response.status_code == 200

    token = response.json()["access_token"]

    return {
        "Authorization": f"Bearer {token}",
    }


def create_job(
    client,
    headers,
    *,
    job_id=None,
    title="Test Job",
    dedup_hash=None,
):
    job_id = job_id or str(uuid.uuid4())

    response = client.post(
        "/api/apps/local/entities/Job",
        headers=headers,
        json={
            "id": job_id,
            "title": title,
            "company": "Test Company",
            "description": "Test job description",
            "dedup_hash": dedup_hash or str(uuid.uuid4()),
            "dismissed": False,
        },
    )

    assert response.status_code == 200

    return response.json()


def test_clear_all_actually_deletes_every_job(
    client,
    temp_db_path,
):
    create_user()

    headers = login_as(client)

    create_job(
        client,
        headers,
        title="Job One",
    )

    create_job(
        client,
        headers,
        title="Job Two",
    )

    create_job(
        client,
        headers,
        title="Job Three",
    )

    before = client.get(
        "/api/apps/local/entities/Job",
        headers=headers,
    )

    assert before.status_code == 200
    assert len(before.json()) == 3

    response = client.delete(
        "/api/apps/local/entities/Job/clear-all",
        headers=headers,
    )

    assert response.status_code == 200

    data = response.json()

    assert data["status"] == "success"

    after = client.get(
        "/api/apps/local/entities/Job",
        headers=headers,
    )

    assert after.status_code == 200
    assert after.json() == []


def test_deleting_a_single_job_by_id_still_works(
    client,
    temp_db_path,
):
    create_user()

    headers = login_as(client)

    job = create_job(
        client,
        headers,
        title="Job To Delete",
    )

    remaining_job = create_job(
        client,
        headers,
        title="Job To Keep",
    )

    response = client.delete(
        f"/api/apps/local/entities/Job/{job['id']}",
        headers=headers,
    )

    assert response.status_code == 200

    data = response.json()

    assert data["status"] == "deleted"

    jobs = client.get(
        "/api/apps/local/entities/Job",
        headers=headers,
    )

    assert jobs.status_code == 200

    jobs_by_id = {
        item["id"]: item
        for item in jobs.json()
    }

    assert job["id"] not in jobs_by_id
    assert remaining_job["id"] in jobs_by_id