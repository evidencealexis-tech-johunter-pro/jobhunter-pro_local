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


def create_test_user():
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
            "user@example.com",
            "Test User",
            hash_password("CorrectHorseBatteryStaple!"),
            now,
            now,
        ),
    )

    conn.commit()
    conn.close()

    return user_id


def test_user_me_requires_authentication(client, temp_db_path):
    response = client.get(
        "/api/apps/local/entities/User/me"
    )

    assert response.status_code == 401


def test_login_returns_access_token(client, temp_db_path):
    create_test_user()

    response = client.post(
        "/api/apps/local/auth/login",
        json={
            "email": "user@example.com",
            "password": "CorrectHorseBatteryStaple!",
        },
    )

    assert response.status_code == 200

    data = response.json()

    assert data["access_token"]
    assert data["token_type"] == "bearer"
    assert data["user"]["email"] == "user@example.com"
    assert data["user"]["name"] == "Test User"


def test_login_rejects_wrong_password(client, temp_db_path):
    create_test_user()

    response = client.post(
        "/api/apps/local/auth/login",
        json={
            "email": "user@example.com",
            "password": "wrong-password",
        },
    )

    assert response.status_code == 401


def test_user_me_returns_authenticated_user(client, temp_db_path):
    create_test_user()

    login = client.post(
        "/api/apps/local/auth/login",
        json={
            "email": "user@example.com",
            "password": "CorrectHorseBatteryStaple!",
        },
    )

    assert login.status_code == 200

    token = login.json()["access_token"]

    response = client.get(
        "/api/apps/local/entities/User/me",
        headers={
            "Authorization": f"Bearer {token}",
        },
    )

    assert response.status_code == 200

    data = response.json()

    assert data["email"] == "user@example.com"
    assert data["name"] == "Test User"
    assert data["is_active"] is True


def test_logout_revokes_access_token(client, temp_db_path):
    create_test_user()

    login = client.post(
        "/api/apps/local/auth/login",
        json={
            "email": "user@example.com",
            "password": "CorrectHorseBatteryStaple!",
        },
    )

    assert login.status_code == 200

    token = login.json()["access_token"]

    logout = client.post(
        "/api/apps/auth/logout",
        headers={
            "Authorization": f"Bearer {token}",
        },
    )

    assert logout.status_code == 200

    response = client.get(
        "/api/apps/local/entities/User/me",
        headers={
            "Authorization": f"Bearer {token}",
        },
    )

    assert response.status_code == 401