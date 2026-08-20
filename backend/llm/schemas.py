from __future__ import annotations

from pydantic import BaseModel


class InvokeLLMRequest(BaseModel):
    prompt: str
    response_json_schema: dict | None = None
    file_urls: list[str] | None = None