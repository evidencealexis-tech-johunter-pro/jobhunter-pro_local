"""
Tests for the authenticated BYOK flow.

These tests verify that API keys are owned by the authenticated user and that
one user's key cannot be read, removed, or used by another user.
"""
import os
import sys
import uuid
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
import main as app_module
from auth import hash_password


def create_user(email: str, password: str = "CorrectHorseBatteryStaple!"):
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
            email.split("@", 1)[0],
            hash_password(password),
            now,
            now,
        ),
    )
    conn.commit()
    conn.close()
    return user_id


def login(client, email: str, password: str = "CorrectHorseBatteryStaple!"):
    """Authenticate in an isolated browser session and return a Bearer token."""
    with TestClient(app_module.app) as auth_client:
        response = auth_client.post(
            "/api/apps/local/auth/login",
            json={"email": email, "password": password},
        )
        assert response.status_code == 200, response.text
        return response.json()["access_token"]
def auth_headers(token: str):
    return {"Authorization": f"Bearer {token}"}


def test_byok_requires_authentication(client, temp_db_path):
    response = client.get("/api/settings/api-key/status")
    assert response.status_code == 401


def test_saving_a_key_for_unsupported_provider_is_rejected(client, temp_db_path):
    create_user("user@example.com")
    token = login(client, "user@example.com")

    response = client.post(
        "/api/settings/api-key",
        headers=auth_headers(token),
        json={
            "api_key": "sk-fake",
            "provider": "not-a-real-provider",
        },
    )
    assert response.status_code == 400


def test_saving_a_valid_key_succeeds_and_does_not_freeze_default_model(
    client,
    temp_db_path,
    monkeypatch,
):
    create_user("user@example.com")
    token = login(client, "user@example.com")

    monkeypatch.setattr(app_module.litellm, "completion", lambda **kwargs: None)

    response = client.post(
        "/api/settings/api-key",
        headers=auth_headers(token),
        json={
            "api_key": "sk-fake-key-1234",
            "provider": "openai",
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "success"

    status = client.get(
        "/api/settings/api-key/status",
        headers=auth_headers(token),
    ).json()

    assert status["active"] is True
    assert status["provider"] == "openai"
    assert status["model"] == app_module.load_config()["default_models"]["openai"]


def test_a_rejected_key_returns_clear_error_not_generic_500(
    client,
    temp_db_path,
    monkeypatch,
):
    create_user("user@example.com")
    token = login(client, "user@example.com")

    def fake_completion_fails(**kwargs):
        raise Exception("Incorrect API key provided")

    monkeypatch.setattr(app_module.litellm, "completion", fake_completion_fails)

    response = client.post(
        "/api/settings/api-key",
        headers=auth_headers(token),
        json={
            "api_key": "sk-bad-key",
            "provider": "openai",
        },
    )

    assert response.status_code == 400
    assert "openai" in response.json()["detail"].lower()


def test_removing_a_key_makes_status_inactive(client, temp_db_path, monkeypatch):
    create_user("user@example.com")
    token = login(client, "user@example.com")

    monkeypatch.setattr(app_module.litellm, "completion", lambda **kwargs: None)

    client.post(
        "/api/settings/api-key",
        headers=auth_headers(token),
        json={"api_key": "sk-fake", "provider": "openai"},
    )

    assert client.get(
        "/api/settings/api-key/status",
        headers=auth_headers(token),
    ).json()["active"] is True

    response = client.delete(
        "/api/settings/api-key",
        headers=auth_headers(token),
    )
    assert response.status_code == 200

    assert client.get(
        "/api/settings/api-key/status",
        headers=auth_headers(token),
    ).json()["active"] is False


def test_users_cannot_see_each_others_keys(client, temp_db_path, monkeypatch):
    create_user("primary@example.com")
    create_user("secondary@example.com")

    primary_token = login(client, "primary@example.com")
    secondary_token = login(client, "secondary@example.com")

    monkeypatch.setattr(app_module.litellm, "completion", lambda **kwargs: None)

    saved = client.post(
        "/api/settings/api-key",
        headers=auth_headers(primary_token),
        json={"api_key": "sk-primary-1234", "provider": "openai"},
    )
    assert saved.status_code == 200

    primary_status = client.get(
        "/api/settings/api-key/status",
        headers=auth_headers(primary_token),
    ).json()
    secondary_status = client.get(
        "/api/settings/api-key/status",
        headers=auth_headers(secondary_token),
    ).json()

    assert primary_status["active"] is True
    assert primary_status["key_suffix"] == "1234"
    assert secondary_status["active"] is False


def test_one_user_cannot_remove_another_users_key(client, temp_db_path, monkeypatch):
    create_user("primary@example.com")
    create_user("secondary@example.com")

    primary_token = login(client, "primary@example.com")
    secondary_token = login(client, "secondary@example.com")

    monkeypatch.setattr(app_module.litellm, "completion", lambda **kwargs: None)

    client.post(
        "/api/settings/api-key",
        headers=auth_headers(primary_token),
        json={"api_key": "sk-primary-1234", "provider": "openai"},
    )

    response = client.delete(
        "/api/settings/api-key",
        headers=auth_headers(secondary_token),
    )
    assert response.status_code == 404

    primary_status = client.get(
        "/api/settings/api-key/status",
        headers=auth_headers(primary_token),
    ).json()
    assert primary_status["active"] is True


def test_generic_user_api_key_entity_access_is_blocked(client, temp_db_path):
    create_user("user@example.com")
    token = login(client, "user@example.com")

    response = client.get(
        "/api/apps/local/entities/UserApiKey",
        headers=auth_headers(token),
    )

    assert response.status_code == 403