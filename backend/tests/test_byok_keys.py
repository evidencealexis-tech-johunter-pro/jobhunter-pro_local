"""
Tests for the user-scoped BYOK key flow.

These tests verify that:
1. BYOK requires authentication.
2. Unsupported providers are rejected.
3. A valid key is stored for the authenticated user.
4. The selected user's key status is returned.
5. A user can remove their own key.
6. One user cannot see another user's key.
7. One user cannot remove another user's key.
"""

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

    token = response.json()["access_token"]

    return {
        "Authorization": f"Bearer {token}",
    }


def test_saving_a_key_requires_authentication(
    client,
    temp_db_path,
):
    response = client.post(
        "/api/settings/api-key",
        json={
            "api_key": "sk-fake",
            "provider": "not-a-real-provider",
        },
    )

    assert response.status_code == 401


def test_saving_a_key_for_unsupported_provider_is_rejected(
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

    response = client.post(
        "/api/settings/api-key",
        headers=headers,
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
    create_user(
        "alice@example.com",
        "Alice",
    )

    headers = login_as(
        client,
        "alice@example.com",
    )

    monkeypatch.setattr(
        app_module.litellm,
        "completion",
        lambda **kwargs: None,
    )

    response = client.post(
        "/api/settings/api-key",
        headers=headers,
        json={
            "api_key": "sk-fake-key-1234",
            "provider": "openai",
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "success"

    status = client.get(
        "/api/settings/api-key/status",
        headers=headers,
    )

    assert status.status_code == 200

    data = status.json()

    assert data["active"] is True
    assert data["provider"] == "openai"

    assert data["model"] == app_module.load_config()[
        "default_models"
    ]["openai"]


def test_a_rejected_key_returns_a_clear_error_not_a_generic_500(
    client,
    temp_db_path,
    monkeypatch,
):
    create_user(
        "alice@example.com",
        "Alice",
    )

    headers = login_as(
        client,
        "alice@example.com",
    )

    def fake_completion_fails(**kwargs):
        raise Exception("Incorrect API key provided")

    monkeypatch.setattr(
        app_module.litellm,
        "completion",
        fake_completion_fails,
    )

    response = client.post(
        "/api/settings/api-key",
        headers=headers,
        json={
            "api_key": "sk-bad-key",
            "provider": "openai",
        },
    )

    assert response.status_code == 400
    assert "openai" in response.json()["detail"].lower()


def test_removing_a_key_makes_status_inactive(
    client,
    temp_db_path,
    monkeypatch,
):
    create_user(
        "alice@example.com",
        "Alice",
    )

    headers = login_as(
        client,
        "alice@example.com",
    )

    monkeypatch.setattr(
        app_module.litellm,
        "completion",
        lambda **kwargs: None,
    )

    save_response = client.post(
        "/api/settings/api-key",
        headers=headers,
        json={
            "api_key": "sk-fake",
            "provider": "openai",
        },
    )

    assert save_response.status_code == 200

    before = client.get(
        "/api/settings/api-key/status",
        headers=headers,
    )

    assert before.status_code == 200
    assert before.json()["active"] is True

    remove_response = client.delete(
        "/api/settings/api-key",
        headers=headers,
    )

    assert remove_response.status_code == 200

    after = client.get(
        "/api/settings/api-key/status",
        headers=headers,
    )

    assert after.status_code == 200
    assert after.json()["active"] is False


def test_users_cannot_see_each_others_api_keys(
    client,
    temp_db_path,
    monkeypatch,
):
    create_user(
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

    monkeypatch.setattr(
        app_module.litellm,
        "completion",
        lambda **kwargs: None,
    )

    response = client.post(
        "/api/settings/api-key",
        headers=alice_headers,
        json={
            "api_key": "alice-secret-key-1234",
            "provider": "openai",
        },
    )

    assert response.status_code == 200

    alice_status = client.get(
        "/api/settings/api-key/status",
        headers=alice_headers,
    )

    assert alice_status.status_code == 200
    assert alice_status.json()["active"] is True
    assert alice_status.json()["key_suffix"] == "1234"

    bob_status = client.get(
        "/api/settings/api-key/status",
        headers=bob_headers,
    )

    assert bob_status.status_code == 200
    assert bob_status.json()["active"] is False


def test_users_cannot_remove_each_others_api_keys(
    client,
    temp_db_path,
    monkeypatch,
):
    create_user(
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

    monkeypatch.setattr(
        app_module.litellm,
        "completion",
        lambda **kwargs: None,
    )

    save_response = client.post(
        "/api/settings/api-key",
        headers=alice_headers,
        json={
            "api_key": "alice-secret-key-1234",
            "provider": "openai",
        },
    )

    assert save_response.status_code == 200

    bob_remove = client.delete(
        "/api/settings/api-key",
        headers=bob_headers,
    )

    assert bob_remove.status_code == 404

    alice_status = client.get(
        "/api/settings/api-key/status",
        headers=alice_headers,
    )

    assert alice_status.status_code == 200
    assert alice_status.json()["active"] is True