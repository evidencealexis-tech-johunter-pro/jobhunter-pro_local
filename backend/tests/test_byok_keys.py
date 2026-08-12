"""
Tests for the BYOK key-saving flow. These lock in two real fixes from
this session: (1) a key is validated against ONLY the provider the user
selected, not a five-provider guessing loop, and (2) a model is only
frozen into storage if the user explicitly chose one - otherwise it
should always resolve to whatever remote_config.py currently says.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main as app_module


def test_saving_a_key_for_unsupported_provider_is_rejected(client, temp_db_path):
    response = client.post("/api/settings/api-key", json={
        "api_key": "sk-fake",
        "provider": "not-a-real-provider",
    })
    assert response.status_code == 400


def test_saving_a_valid_key_succeeds_and_does_not_freeze_default_model(client, temp_db_path, monkeypatch):
    def fake_completion(**kwargs):
        return None  # success = no exception raised

    monkeypatch.setattr(app_module.litellm, "completion", fake_completion)

    response = client.post("/api/settings/api-key", json={
        "api_key": "sk-fake-key-1234",
        "provider": "openai",
    })
    assert response.status_code == 200
    assert response.json()["status"] == "success"

    status = client.get("/api/settings/api-key/status").json()
    assert status["active"] is True
    assert status["provider"] == "openai"
    # THE FIX: no explicit model was given, so the model shown should come
    # from the CURRENT config, not a value frozen in at save time.
    assert status["model"] == app_module.load_config()["default_models"]["openai"]


def test_a_rejected_key_returns_a_clear_error_not_a_generic_500(client, temp_db_path, monkeypatch):
    def fake_completion_fails(**kwargs):
        raise Exception("Incorrect API key provided")

    monkeypatch.setattr(app_module.litellm, "completion", fake_completion_fails)

    response = client.post("/api/settings/api-key", json={
        "api_key": "sk-bad-key",
        "provider": "openai",
    })
    assert response.status_code == 400
    assert "openai" in response.json()["detail"].lower()


def test_removing_a_key_makes_status_inactive(client, temp_db_path, monkeypatch):
    monkeypatch.setattr(app_module.litellm, "completion", lambda **kwargs: None)
    client.post("/api/settings/api-key", json={"api_key": "sk-fake", "provider": "openai"})
    assert client.get("/api/settings/api-key/status").json()["active"] is True

    response = client.delete("/api/settings/api-key")
    assert response.status_code == 200

    assert client.get("/api/settings/api-key/status").json()["active"] is False