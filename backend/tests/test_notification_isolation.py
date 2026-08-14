"""
Notification ownership and isolation tests.

These prove that notifications are owned by the authenticated user and
cannot be read, marked read, cleared, or manipulated by another user.
"""

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
    response = client.post(
        "/api/apps/local/auth/login",
        json={
            "email": email,
            "password": TEST_PASSWORD,
        },
    )

    assert response.status_code == 200

    return {
        "Authorization": f"Bearer {response.json()['access_token']}",
    }


def test_notifications_require_authentication(
    client,
    temp_db_path,
):
    response = client.get("/api/notifications")

    assert response.status_code == 401


def test_notification_creation_is_bound_to_authenticated_user(
    client,
    temp_db_path,
):
    alice_id = create_user(
        "alice@example.com",
        "Alice",
    )

    headers = login_as(
        client,
        "alice@example.com",
    )

    app_module.add_notification(
        "Alice notification",
        type="info",
        user_id=alice_id,
    )

    response = client.get(
        "/api/notifications",
        headers=headers,
    )

    assert response.status_code == 200

    notifications = response.json()["notifications"]

    assert len(notifications) == 1
    assert notifications[0]["user_id"] == alice_id
    assert notifications[0]["message"] == "Alice notification"


def test_users_cannot_see_each_others_notifications(
    client,
    temp_db_path,
):
    alice_id = create_user(
        "alice@example.com",
        "Alice",
    )

    create_user(
        "bob@example.com",
        "Bob",
    )

    alice_headers = login_as(
        client,
        "alice@example.com",
    )

    bob_headers = login_as(
        client,
        "bob@example.com",
    )

    app_module.add_notification(
        "Alice private notification",
        type="info",
        user_id=alice_id,
    )

    alice_response = client.get(
        "/api/notifications",
        headers=alice_headers,
    )

    bob_response = client.get(
        "/api/notifications",
        headers=bob_headers,
    )

    assert alice_response.status_code == 200
    assert bob_response.status_code == 200

    assert len(alice_response.json()["notifications"]) == 1
    assert alice_response.json()["notifications"][0]["message"] == (
        "Alice private notification"
    )

    assert bob_response.json()["notifications"] == []
    assert bob_response.json()["unread_count"] == 0


def test_mark_all_read_only_affects_authenticated_users_notifications(
    client,
    temp_db_path,
):
    alice_id = create_user(
        "alice@example.com",
        "Alice",
    )

    bob_id = create_user(
        "bob@example.com",
        "Bob",
    )

    alice_headers = login_as(
        client,
        "alice@example.com",
    )

    bob_headers = login_as(
        client,
        "bob@example.com",
    )

    app_module.add_notification(
        "Alice notification",
        type="info",
        user_id=alice_id,
    )

    app_module.add_notification(
        "Bob notification",
        type="info",
        user_id=bob_id,
    )

    response = client.post(
        "/api/notifications/mark-all-read",
        headers=alice_headers,
    )

    assert response.status_code == 200

    alice_notifications = client.get(
        "/api/notifications",
        headers=alice_headers,
    )

    bob_notifications = client.get(
        "/api/notifications",
        headers=bob_headers,
    )

    assert alice_notifications.status_code == 200
    assert bob_notifications.status_code == 200

    assert alice_notifications.json()["unread_count"] == 0
    assert bob_notifications.json()["unread_count"] == 1


def test_clear_notifications_only_affects_authenticated_users_notifications(
    client,
    temp_db_path,
):
    alice_id = create_user(
        "alice@example.com",
        "Alice",
    )

    bob_id = create_user(
        "bob@example.com",
        "Bob",
    )

    alice_headers = login_as(
        client,
        "alice@example.com",
    )

    bob_headers = login_as(
        client,
        "bob@example.com",
    )

    app_module.add_notification(
        "Alice notification",
        type="info",
        user_id=alice_id,
    )

    app_module.add_notification(
        "Bob notification",
        type="info",
        user_id=bob_id,
    )

    response = client.delete(
        "/api/notifications",
        headers=alice_headers,
    )

    assert response.status_code == 200

    alice_notifications = client.get(
        "/api/notifications",
        headers=alice_headers,
    )

    bob_notifications = client.get(
        "/api/notifications",
        headers=bob_headers,
    )

    assert alice_notifications.status_code == 200
    assert bob_notifications.status_code == 200

    assert alice_notifications.json()["notifications"] == []

    assert [
        notification["message"]
        for notification in bob_notifications.json()["notifications"]
    ] == ["Bob notification"]


def test_generic_notification_entity_access_is_blocked(
    client,
    temp_db_path,
):
    create_user(
        "alice@example.com",
        "Alice",
    )

    headers = login_as(
        client,
        "alice@example.com",
    )

    get_response = client.get(
        "/api/apps/local/entities/Notification",
        headers=headers,
    )

    post_response = client.post(
        "/api/apps/local/entities/Notification",
        headers=headers,
        json={
            "message": "should not be accepted",
        },
    )

    delete_response = client.delete(
        "/api/apps/local/entities/Notification/some-id",
        headers=headers,
    )

    assert get_response.status_code == 403
    assert post_response.status_code == 403
    assert delete_response.status_code == 403