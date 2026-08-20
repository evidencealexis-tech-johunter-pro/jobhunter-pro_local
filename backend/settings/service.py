from __future__ import annotations

import json

import litellm
from fastapi import HTTPException
from pydantic import BaseModel

from encryption import decrypt_api_key, detect_provider_from_key, encrypt_api_key
from remote_config import load_config

from .repository import (
    create_active_key,
    expire_active_keys,
    find_active_key,
    revoke_active_key,
)


class SaveApiKeyRequest(BaseModel):
    api_key: str
    provider: str | None = None
    model: str | None = None
    base_url: str | None = None
    label: str = "Default"


def friendly_provider_error(
    error: Exception,
    provider: str | None = None,
) -> str:
    message = str(error).lower()

    if (
        "incorrect api key" in message
        or "api key not valid" in message
        or "authentication" in message
        or "401" in message
    ):
        base = "Invalid API key"
    elif "403" in message or "permission" in message:
        base = "That key does not have permission to use this model"
    elif "404" in message or "not found" in message:
        base = "Provider endpoint not found"
    elif "405" in message or "method not allowed" in message:
        base = "Provider rejected the request"
    elif (
        "429" in message
        or "rate limit" in message
        or "resource_exhausted" in message
    ):
        base = "Rate limit hit"
    elif (
        "insufficient balance" in message
        or "quota" in message
        or "billing" in message
    ):
        base = "Your account has no credits or has hit its spending limit"
    elif "timeout" in message or "connection" in message:
        base = "Could not reach the provider"
    else:
        base = "That key was rejected"

    suffix = " Please verify your provider, model, and key."
    return f"{base} by {provider}.{suffix}" if provider else f"{base}.{suffix}"


def _validate_provider_request(
    provider: str | None,
    model: str | None,
    base_url: str | None,
) -> tuple[dict, str | None, str | None, str | None]:
    config = load_config()

    if provider == "custom":
        if not base_url:
            raise HTTPException(
                status_code=400,
                detail="Base URL is required for a custom provider",
            )
        if not model:
            raise HTTPException(
                status_code=400,
                detail="Model name is required for a custom provider",
            )
        return config, provider, model, base_url

    if provider and provider != "auto":
        if provider not in config["supported_providers"]:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported provider: {provider}",
            )

        selected_model = model or config["default_models"].get(provider)
        if not selected_model:
            raise HTTPException(
                status_code=400,
                detail=f"No default model configured for {provider}",
            )
        return config, provider, selected_model, base_url

    return config, provider, model, base_url


def _verify_provider_key(
    *,
    api_key: str,
    provider: str,
    model: str,
    base_url: str | None = None,
) -> None:
    kwargs = {
        "model": model,
        "api_key": api_key,
        "messages": [{"role": "user", "content": "test"}],
        "max_tokens": 1,
        "timeout": 10,
    }
    if base_url:
        kwargs["api_base"] = base_url

    try:
        litellm.completion(**kwargs)
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=friendly_provider_error(exc, provider=provider),
        ) from exc


def _store_key(
    api_key: str,
    user_id: str,
    provider: str,
    model: str | None,
    label: str,
    base_url: str | None = None,
) -> None:
    encrypted = encrypt_api_key(api_key)
    suffix = api_key[-4:] if len(api_key) >= 4 else "****"
    create_active_key(
        user_id=user_id,
        provider=provider,
        encrypted_key=encrypted,
        key_suffix=suffix,
        model=model,
        label=label,
        base_url=base_url,
    )


def save_api_key(
    body: SaveApiKeyRequest,
    user_id: str,
) -> dict:
    api_key = body.api_key.strip()
    provider = body.provider.strip().lower() if body.provider else None
    model = body.model.strip() if body.model else None
    base_url = body.base_url.strip() if body.base_url else None

    if not api_key:
        raise HTTPException(status_code=400, detail="API key is required")

    config, provider, model, base_url = _validate_provider_request(
        provider, model, base_url
    )

    if provider == "custom":
        _verify_provider_key(
            api_key=api_key,
            provider=provider,
            model=f"openai/{model}",
            base_url=base_url,
        )
        _store_key(
            api_key,
            user_id,
            provider="custom",
            model=model,
            label=body.label,
            base_url=base_url,
        )
        return {
            "status": "success",
            "message": "Custom provider key saved and activated",
        }

    if provider and provider != "auto":
        full_model = model if "/" in model else f"{provider}/{model}"
        _verify_provider_key(
            api_key=api_key,
            provider=provider,
            model=full_model,
        )
        _store_key(
            api_key,
            user_id,
            provider=provider,
            model=body.model.strip() if body.model else None,
            label=body.label,
        )
        return {
            "status": "success",
            "message": f"{provider} key saved and activated",
        }

    detected = detect_provider_from_key(api_key)

    if not detected:
        for candidate in config["supported_providers"]:
            if candidate == "custom":
                continue
            candidate_model = config["default_models"].get(candidate)
            if not candidate_model:
                continue
            try:
                litellm.completion(
                    model=candidate_model,
                    api_key=api_key,
                    messages=[{"role": "user", "content": "test"}],
                    max_tokens=1,
                    timeout=10,
                )
                detected = candidate
                break
            except Exception:
                continue

    if not detected:
        return {
            "status": "provider_required",
            "message": (
                "Couldn't determine which provider this key belongs to. "
                "Please select it manually."
            ),
            "providers": config["providers"],
        }

    _store_key(
        api_key,
        user_id,
        provider=detected,
        model=None,
        label=body.label,
    )
    return {
        "status": "success",
        "message": f"Detected {detected} - key saved and activated",
    }


def remove_api_key(user_id: str) -> dict:
    if not revoke_active_key(user_id):
        raise HTTPException(
            status_code=404,
            detail="No active key to remove",
        )
    return {"status": "success", "message": "Key removed"}


def api_key_status(user_id: str) -> dict:
    row = find_active_key(user_id)
    if not row:
        return {
            "active": False,
            "provider": None,
            "model": None,
            "key_suffix": None,
        }

    key_data = json.loads(row["data"])
    provider = key_data["provider"]
    model = (
        key_data.get("model")
        or load_config()["default_models"].get(provider, "")
    )
    return {
        "active": True,
        "provider": provider,
        "model": model,
        "key_suffix": key_data.get("key_suffix", "****"),
    }


def get_providers() -> dict:
    config = load_config()
    return {
        "providers": config["providers"],
        "default_models": config["default_models"],
    }


def get_active_llm_credentials(user_id: str):
    row = find_active_key(user_id)
    if not row:
        raise HTTPException(
            status_code=400,
            detail="No active API key. Add one in Settings.",
        )

    key_data = json.loads(row["data"])
    provider = key_data["provider"]
    model = key_data.get("model") or load_config()["default_models"].get(
        provider, ""
    )
    api_key = decrypt_api_key(key_data["encrypted_key"])
    return provider, api_key, model


def mark_user_key_expired(user_id: str) -> None:
    expire_active_keys(user_id)