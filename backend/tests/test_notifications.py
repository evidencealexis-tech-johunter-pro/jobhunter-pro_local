import os
import sys
import uuid
from datetime import datetime, timezone
from notifications.service import add_notification

sys.path.insert(
    0,
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
)

import main as app_module
app_module.add_notification = add_notification
from auth import hash_password


TEST_PASSWORD = "CorrectHorseBatteryStaple!"


def create_user(
    email="test@example.com",
    name="Test User",
):
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


def login_as(
    client,
    email="test@example.com",
):
    response = client.post(
        "/api/apps/local/auth/login",
        json={
            "email": email,
            "password": TEST_PASSWORD,
        },
    )

    assert response.status_code == 200

    return {
        "Authorization": (
            f"Bearer {response.json()['access_token']}"
        ),
    }


def test_notification_appears_after_being_added(
    client,
    temp_db_path,
):
    user_id = create_user()

    headers = login_as(client)

    app_module.add_notification(
        "Test scan finished",
        type="success",
        user_id=user_id,
    )

    response = client.get(
        "/api/notifications",
        headers=headers,
    )

    assert response.status_code == 200

    data = response.json()

    assert data["unread_count"] == 1
    assert len(data["notifications"]) == 1
    assert data["notifications"][0]["message"] == (
        "Test scan finished"
    )
    assert data["notifications"][0]["type"] == "success"


def test_mark_all_read_clears_unread_count(
    client,
    temp_db_path,
):
    user_id = create_user()

    headers = login_as(client)

    app_module.add_notification(
        "First",
        type="info",
        user_id=user_id,
    )

    app_module.add_notification(
        "Second",
        type="info",
        user_id=user_id,
    )

    before = client.get(
        "/api/notifications",
        headers=headers,
    )

    assert before.status_code == 200
    assert before.json()["unread_count"] == 2

    response = client.post(
        "/api/notifications/mark-all-read",
        headers=headers,
    )

    assert response.status_code == 200

    after = client.get(
        "/api/notifications",
        headers=headers,
    )

    assert after.status_code == 200
    assert after.json()["unread_count"] == 0


def test_clear_all_notifications_empties_the_list(
    client,
    temp_db_path,
):
    user_id = create_user()

    headers = login_as(client)

    app_module.add_notification(
        "Something happened",
        type="info",
        user_id=user_id,
    )

    before = client.get(
        "/api/notifications",
        headers=headers,
    )

    assert before.status_code == 200
    assert len(before.json()["notifications"]) == 1

    response = client.delete(
        "/api/notifications",
        headers=headers,
    )

    assert response.status_code == 200

    after = client.get(
        "/api/notifications",
        headers=headers,
    )

    assert after.status_code == 200
    assert after.json()["notifications"] == []
    assert after.json()["unread_count"] == 0


def test_notifications_sorted_most_recent_first(
    client,
    temp_db_path,
):
    user_id = create_user()

    headers = login_as(client)

    app_module.add_notification(
        "Oldest",
        type="info",
        user_id=user_id,
    )

    app_module.add_notification(
        "Newest",
        type="success",
        user_id=user_id,
    )

    response = client.get(
        "/api/notifications",
        headers=headers,
    )

    assert response.status_code == 200

    messages = [
        notification["message"]
        for notification in response.json()["notifications"]
    ]

    assert messages == [
        "Newest",
        "Oldest",
    ]