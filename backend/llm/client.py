from __future__ import annotations

import json
from typing import Any

import litellm


def completion(
    *,
    model: str,
    api_key: str,
    system_prompt: str,
    user_prompt: str,
) -> dict[str, Any]:
    response = litellm.completion(
        model=model,
        api_key=api_key,
        messages=[
            {
                "role": "system",
                "content": system_prompt,
            },
            {
                "role": "user",
                "content": user_prompt,
            },
        ],
        temperature=0.1,
        response_format={
            "type": "json_object",
        },
    )

    return json.loads(
        response.choices[0].message.content
    )


async def acompletion(
    *,
    model: str,
    api_key: str,
    system_prompt: str,
    user_prompt: str,
) -> dict[str, Any]:
    response = await litellm.acompletion(
        model=model,
        api_key=api_key,
        messages=[
            {
                "role": "system",
                "content": system_prompt,
            },
            {
                "role": "user",
                "content": user_prompt,
            },
        ],
        temperature=0.1,
        response_format={
            "type": "json_object",
        },
    )

    return json.loads(
        response.choices[0].message.content
    )