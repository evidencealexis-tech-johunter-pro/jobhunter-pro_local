"""
Regression test for a real bug: call_llm_with_retry_async used to wait
out a rate-limit delay and then STILL return None, because the old
`for attempt in range(max_retries)` loop had no second iteration
available when every call site used the old default of max_retries=1.

This test simulates a call that fails twice with a rate-limit error and
then succeeds on the third try, and asserts the function actually
returns the successful result instead of giving up after the first wait.
"""
import sys
import os
import json
import pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main as app_module


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
        self.choices = [FakeChoice(content)]


@pytest.mark.asyncio
async def test_retries_actually_happen_after_a_rate_limit_wait(monkeypatch, temp_db_path):
    call_count = {"n": 0}

    async def fake_acompletion(**kwargs):
        call_count["n"] += 1
        if call_count["n"] < 3:
            raise FakeRateLimitError()
        return FakeResponse(json.dumps({"skills_score": 80}))

    async def fake_sleep(seconds):
        return  # skip real waiting in tests

    def fake_get_active_llm_credentials():
        return "openai", "fake-key", "openai/gpt-4o-mini"

    monkeypatch.setattr(app_module.litellm, "acompletion", fake_acompletion)
    monkeypatch.setattr(app_module.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(app_module, "get_active_llm_credentials", fake_get_active_llm_credentials)

    result = await app_module.call_llm_with_retry_async(
        system_prompt="test", user_prompt="test", max_retries=3
    )

    assert call_count["n"] == 3, "Expected exactly 3 attempts (2 failures + 1 success)"
    assert result == {"skills_score": 80}, (
        "The call eventually succeeded but the function returned None - "
        "this is the exact bug where a rate-limit wait led nowhere."
    )


@pytest.mark.asyncio
async def test_gives_up_cleanly_after_exhausting_all_retries(monkeypatch, temp_db_path):
    async def always_fails(**kwargs):
        raise FakeRateLimitError()

    async def fake_sleep(seconds):
        return

    def fake_get_active_llm_credentials():
        return "openai", "fake-key", "openai/gpt-4o-mini"

    monkeypatch.setattr(app_module.litellm, "acompletion", always_fails)
    monkeypatch.setattr(app_module.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(app_module, "get_active_llm_credentials", fake_get_active_llm_credentials)

    result = await app_module.call_llm_with_retry_async(
        system_prompt="test", user_prompt="test", max_retries=3
    )

    assert result is None  # correctly gives up ONLY after real attempts, not silently