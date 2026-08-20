from __future__ import annotations

from pydantic import BaseModel, Field

from jobs.config import (
    DEFAULT_DOMAIN_WEIGHT,
    DEFAULT_MATCH_THRESHOLD,
    DEFAULT_SEMANTIC_WEIGHT,
    DEFAULT_SENIORITY_WEIGHT,
    DEFAULT_SKILLS_WEIGHT,
)


class ScrapeJobsRequest(BaseModel):
    source_url: str = Field(min_length=1)
    source_name: str | None = None

    match_threshold: int = DEFAULT_MATCH_THRESHOLD
    skills_weight: int = DEFAULT_SKILLS_WEIGHT
    semantic_weight: int = DEFAULT_SEMANTIC_WEIGHT
    seniority_weight: int = DEFAULT_SENIORITY_WEIGHT
    domain_weight: int = DEFAULT_DOMAIN_WEIGHT