"""
Notification ownership and isolation tests.

These verify that notification records are server-owned by the authenticated
user and that one user cannot read, mark, or clear another user's notices.
"""

import os
import sys
import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

sys.path.insert(
    0,
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
)

import main as app_module
from notifications.service import add_notification
app_module.add_notification = add_notification
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
def test_notifications_require_authentication(client, temp_db_path):
    response = client.get("/api/notifications")
    assert response.status_code == 401


def test_notification_creation_requires_owner_and_isolated_reads(
    client,
    temp_db_path,
):
    primary_user_id = create_user("primary@example.com", "Primary")
    create_user("secondary@example.com", "Secondary")

    primary_headers = login_as(client, "primary@example.com")
    secondary_headers = login_as(client, "secondary@example.com")

    app_module.add_notification(
        "Primary notification",
        user_id=primary_user_id,
        type="info",
    )

    primary_response = client.get(
        "/api/notifications",
        headers=primary_headers,
    )
    secondary_response = client.get(
        "/api/notifications",
        headers=secondary_headers,
    )

    assert primary_response.status_code == 200
    assert secondary_response.status_code == 200

    primary_items = primary_response.json()["notifications"]
    secondary_items = secondary_response.json()["notifications"]

    assert len(primary_items) == 1
    assert primary_items[0]["message"] == "Primary notification"
    assert primary_items[0]["user_id"] == primary_user_id
    assert secondary_items == []


def test_users_cannot_mark_each_others_notifications_as_read(
    client,
    temp_db_path,
):
    primary_user_id = create_user("primary@example.com", "Primary")
    create_user("secondary@example.com", "Secondary")

    primary_headers = login_as(client, "primary@example.com")
    secondary_headers = login_as(client, "secondary@example.com")

    app_module.add_notification(
        "Primary unread",
        user_id=primary_user_id,
        type="info",
    )

    before = client.get(
        "/api/notifications",
        headers=primary_headers,
    )
    assert before.json()["unread_count"] == 1

    secondary_mark = client.post(
        "/api/notifications/mark-all-read",
        headers=secondary_headers,
    )
    assert secondary_mark.status_code == 200

    after = client.get(
        "/api/notifications",
        headers=primary_headers,
    )
    assert after.status_code == 200
    assert after.json()["unread_count"] == 1
    assert after.json()["notifications"][0]["read"] is False


def test_clear_notifications_only_clears_the_authenticated_users_notifications(
    client,
    temp_db_path,
):
    primary_user_id = create_user("primary@example.com", "Primary")
    secondary_user_id = create_user("secondary@example.com", "Secondary")

    primary_headers = login_as(client, "primary@example.com")
    secondary_headers = login_as(client, "secondary@example.com")

    app_module.add_notification(
        "Primary notice",
        user_id=primary_user_id,
        type="info",
    )
    app_module.add_notification(
        "Secondary notice",
        user_id=secondary_user_id,
        type="info",
    )

    response = client.delete(
        "/api/notifications",
        headers=primary_headers,
    )
    assert response.status_code == 200

    primary_items = client.get(
        "/api/notifications",
        headers=primary_headers,
    ).json()["notifications"]
    secondary_items = client.get(
        "/api/notifications",
        headers=secondary_headers,
    ).json()["notifications"]

    assert primary_items == []
    assert len(secondary_items) == 1
    assert secondary_items[0]["message"] == "Secondary notice"


def test_generic_notification_entity_access_is_blocked(
    client,
    temp_db_path,
):
    create_user("primary@example.com", "Primary")
    headers = login_as(client, "primary@example.com")

    for method, path in [
        ("get", "/api/apps/local/entities/Notification"),
        ("post", "/api/apps/local/entities/Notification"),
        ("delete", "/api/apps/local/entities/Notification/some-id"),
    ]:
        if method == "post":
            response = client.post(
                path,
                headers=headers,
                json={"message": "should not be accepted"},
            )
        elif method == "get":
            response = client.get(
                path,
                headers=headers,
            )
        else:
            response = client.delete(
                path,
                headers=headers,
            )
        assert response.status_code == 403


def test_background_notification_carries_scrape_owner(
    client,
    temp_db_path,
):
    primary_user_id = create_user("primary@example.com", "Primary")
    create_user("secondary@example.com", "Secondary")

    primary_headers = login_as(client, "primary@example.com")
    secondary_headers = login_as(client, "secondary@example.com")

    app_module.add_notification(
        "Primary scrape finished",
        user_id=primary_user_id,
        type="success",
        context="scrape",
    )

    primary_items = client.get(
        "/api/notifications",
        headers=primary_headers,
    ).json()["notifications"]
    secondary_items = client.get(
        "/api/notifications",
        headers=secondary_headers,
    ).json()["notifications"]

    assert primary_items[0]["context"] == "scrape"
    assert primary_items[0]["user_id"] == primary_user_id
    assert secondary_items == []