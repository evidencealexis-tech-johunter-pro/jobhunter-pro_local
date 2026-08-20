from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import Any

from fastapi import HTTPException

from core.config import RATE_LIMIT_SECONDS
from encryption import decrypt_api_key
from file_storage import get_owned_file
from llm.client import acompletion, completion
from notifications.service import add_notification
from pdf_extraction import extract_text_from_pdf
from remote_config import load_config
from settings.service import (
    get_active_llm_credentials as default_credentials_resolver,
    mark_user_key_expired,
)


CredentialsResolver = Callable[
    [str],
    tuple[str, str, str],
]


def _retry_delay_from_error(
    error_text: str,
) -> int:
    if "retryDelay" not in error_text:
        return 30

    try:
        return int(
            error_text.split(
                "retryDelay': '"
            )[1].split("s'")[0]
        )
    except (IndexError, ValueError):
        return 30


def _is_authentication_error(
    error_text: str,
) -> bool:
    normalized = error_text.lower()

    return (
        "401" in normalized
        or "403" in normalized
        or "invalid" in normalized
    )


def _is_rate_limit_error(
    error_text: str,
) -> bool:
    normalized = error_text.upper()

    return (
        "429" in normalized
        or "RESOURCE_EXHAUSTED" in normalized
    )


def _resolve_credentials(
    user_id: str,
    credentials_resolver: CredentialsResolver | None,
) -> tuple[str, str, str]:
    resolver = (
        credentials_resolver
        or default_credentials_resolver
    )

    return resolver(user_id)


def _handle_expired_key(
    user_id: str,
    error: Exception,
) -> None:
    mark_user_key_expired(user_id)

    add_notification(
        (
            "Your API key has expired "
            "or was rejected. Add a new one "
            "in Settings."
        ),
        user_id=user_id,
        type="error",
    )

    raise HTTPException(
        status_code=400,
        detail=(
            "Your API key has expired. "
            "Please enter a new key in Settings."
        ),
    ) from error


def call_llm_with_retry(
    *,
    system_prompt: str = "",
    user_prompt: str = "",
    max_retries: int = 3,
    model: str | None = None,
    user_id: str | None = None,
    credentials_resolver: CredentialsResolver | None = None,
) -> dict[str, Any] | None:
    time.sleep(RATE_LIMIT_SECONDS)

    if not user_id:
        raise HTTPException(
            status_code=401,
            detail="Authentication required",
        )

    _provider, api_key, active_model = (
        _resolve_credentials(
            user_id,
            credentials_resolver,
        )
    )

    model = model or active_model
    attempt = 0

    while attempt < max_retries:
        try:
            return completion(
                model=model,
                api_key=api_key,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
            )
        except Exception as exc:
            error_text = str(exc)

            if _is_authentication_error(error_text):
                _handle_expired_key(
                    user_id,
                    exc,
                )

            attempt += 1

            if _is_rate_limit_error(error_text):
                if attempt >= max_retries:
                    return None

                time.sleep(
                    _retry_delay_from_error(
                        error_text
                    )
                )
                continue

            if attempt < max_retries:
                time.sleep(5)
                continue

            return None

    return None


async def call_llm_with_retry_async(
    *,
    system_prompt: str = "",
    user_prompt: str = "",
    max_retries: int = 3,
    model: str | None = None,
    user_id: str | None = None,
    credentials_resolver: CredentialsResolver | None = None,
) -> dict[str, Any] | None:
    await asyncio.sleep(RATE_LIMIT_SECONDS)

    if not user_id:
        raise HTTPException(
            status_code=401,
            detail="Authentication required",
        )

    _provider, api_key, active_model = (
        _resolve_credentials(
            user_id,
            credentials_resolver,
        )
    )

    model = model or active_model
    attempt = 0

    while attempt < max_retries:
        try:
            return await acompletion(
                model=model,
                api_key=api_key,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
            )
        except Exception as exc:
            error_text = str(exc)

            if _is_authentication_error(error_text):
                mark_user_key_expired(user_id)
                return None

            attempt += 1

            if _is_rate_limit_error(error_text):
                if attempt >= max_retries:
                    return None

                await asyncio.sleep(
                    _retry_delay_from_error(
                        error_text
                    )
                )
                continue

            if attempt < max_retries:
                await asyncio.sleep(5)
                continue

            return None

    return None


async def invoke_llm(
    *,
    prompt: str,
    response_json_schema: dict | None,
    file_urls: list[str] | None,
    user_id: str,
    credentials_resolver: CredentialsResolver | None = None,
) -> dict[str, Any]:
    if not prompt:
        raise HTTPException(
            status_code=400,
            detail="Missing 'prompt' in request body.",
        )

    file_text = ""

    if file_urls:
        conn = None

        try:
            from core.database import get_db

            conn = get_db()

            for file_reference in file_urls:
                stored_file = get_owned_file(
                    conn,
                    user_id=user_id,
                    file_reference=file_reference,
                )

                extraction_result = (
                    extract_text_from_pdf(
                        str(
                            stored_file.storage_path
                        )
                    )
                )

                if extraction_result["success"]:
                    file_text += (
                        "\n\n"
                        + extraction_result["text"]
                    )
        finally:
            if conn is not None:
                conn.close()

    schema_instruction = ""

    if response_json_schema:
        import json

        schema_instruction = (
            "\n\nReturn ONLY a valid JSON object "
            "matching this exact schema, no markdown "
            "or extra text:\n"
            + json.dumps(
                response_json_schema
            )
        )

    user_content = (
        prompt
        + schema_instruction
    )

    if file_text:
        user_content += (
            "\n\n=== ATTACHED DOCUMENT CONTENT ===\n"
            + file_text
        )

    from datetime import date

    system_prompt = (
        f"Today's date is "
        f"{date.today().strftime('%B %d, %Y')}. "
        "You are an honest, skeptical, "
        "evidence-based expert assistant. "
        "Never inflate scores. "
        "Return ONLY valid JSON."
    )

    result = await asyncio.to_thread(
        call_llm_with_retry,
        system_prompt=system_prompt,
        user_prompt=user_content,
        user_id=user_id,
        credentials_resolver=credentials_resolver,
    )

    if result:
        result["status"] = "success"

        add_notification(
            "AI analysis completed successfully.",
            user_id=user_id,
            type="success",
        )

        return result

    add_notification(
        (
            "AI analysis failed. "
            "Check your API key and quota."
        ),
        user_id=user_id,
        type="error",
    )

    raise HTTPException(
        status_code=500,
        detail=(
            "LLM call failed. "
            "Check your API key and quota."
        ),
    )