"""
Regression tests for the asynchronous LLM retry logic.

The current LLM credential lookup is user-scoped, so these tests provide
the user_id expected by the production helper while mocking the credential
lookup itself.
"""

import json
import os
import sys

import pytest

sys.path.insert(
    0,
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
)
import main as app_module
from notifications.service import add_notification


class FakeRateLimitError(Exception):
    def __str__(self):
        return "litellm.RateLimitError: 429 rate limited"


class FakeMessage:
    def __init__(self, content):
        self.content = content


class FakeChoice:
    def __init__(self, content):
        self.message = FakeMessage(content)


class FakeResponse:
    def __init__(self, content):
        self.choices = [
            FakeChoice(content)
        ]


TEST_USER_ID = "retry-test-user"


@pytest.mark.asyncio
async def test_retries_actually_happen_after_a_rate_limit_wait(
    monkeypatch,
    temp_db_path,
):
    call_count = {"n": 0}

    async def fake_acompletion(**kwargs):
        call_count["n"] += 1

        if call_count["n"] < 3:
            raise FakeRateLimitError()

        return FakeResponse(
            json.dumps(
                {
                    "skills_score": 80
                }
            )
        )

    async def fake_sleep(seconds):
        return

    def fake_get_active_llm_credentials(user_id):
        assert user_id == TEST_USER_ID

        return (
            "openai",
            "fake-key",
            "openai/gpt-4o-mini",
        )

    monkeypatch.setattr(
        app_module.litellm,
        "acompletion",
        fake_acompletion,
    )

    monkeypatch.setattr(
        app_module.asyncio,
        "sleep",
        fake_sleep,
    )

    monkeypatch.setattr(
        app_module,
        "get_active_llm_credentials",
        fake_get_active_llm_credentials,
    )

    result = await app_module.call_llm_with_retry_async(
        system_prompt="test",
        user_prompt="test",
        max_retries=3,
        user_id=TEST_USER_ID,
    )

    assert call_count["n"] == 3

    assert result == {
        "skills_score": 80
    }


@pytest.mark.asyncio
async def test_gives_up_cleanly_after_exhausting_all_retries(
    monkeypatch,
    temp_db_path,
):
    call_count = {"n": 0}

    async def always_fails(**kwargs):
        call_count["n"] += 1
        raise FakeRateLimitError()

    async def fake_sleep(seconds):
        return

    def fake_get_active_llm_credentials(user_id):
        assert user_id == TEST_USER_ID

        return (
            "openai",
            "fake-key",
            "openai/gpt-4o-mini",
        )

    monkeypatch.setattr(
        app_module.litellm,
        "acompletion",
        always_fails,
    )

    monkeypatch.setattr(
        app_module.asyncio,
        "sleep",
        fake_sleep,
    )

    monkeypatch.setattr(
        app_module,
        "get_active_llm_credentials",
        fake_get_active_llm_credentials,
    )

    result = await app_module.call_llm_with_retry_async(
        system_prompt="test",
        user_prompt="test",
        max_retries=3,
        user_id=TEST_USER_ID,
    )

    assert result is None

    assert call_count["n"] == 3