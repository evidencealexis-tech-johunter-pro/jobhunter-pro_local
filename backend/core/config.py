from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


BACKEND_DIR = Path(__file__).resolve().parents[1]
load_dotenv(dotenv_path=BACKEND_DIR / ".env", override=True)

DEFAULT_DATABASE_PATH = Path("jobhunter_pro.db")
DATABASE_PATH = Path(
    os.getenv("DATABASE_PATH", str(DEFAULT_DATABASE_PATH))
)

SQLITE_BUSY_TIMEOUT_MS = int(
    os.getenv("SQLITE_BUSY_TIMEOUT_MS", "5000")
)

DEFAULT_RATE_LIMIT_SECONDS = 4.0
RATE_LIMIT_SECONDS = float(
    os.getenv("RATE_LIMIT_SECONDS", str(DEFAULT_RATE_LIMIT_SECONDS))
)

PREFILTER_ENABLED = (
    os.getenv("PREFILTER_ENABLED", "false").strip().lower() == "true"
)
APP_DEBUG = (
    os.getenv("APP_DEBUG", "false").strip().lower() == "true"
)

DEFAULT_CORS_ALLOWED_ORIGINS = (
    "http://127.0.0.1:5173",
    "http://localhost:5173",
)


def _parse_allowed_origins() -> tuple[str, ...]:
    configured = os.getenv("CORS_ALLOWED_ORIGINS")
    if not configured:
        return DEFAULT_CORS_ALLOWED_ORIGINS

    return tuple(
        origin.strip().rstrip("/")
        for origin in configured.split(",")
        if origin.strip()
    )


ALLOWED_CORS_ORIGINS = _parse_allowed_origins()

ACCESS_TOKEN_TTL_MINUTES = int(
    os.getenv("ACCESS_TOKEN_TTL_MINUTES", "30")
)

AUTH_COOKIE_SECURE = (
    os.getenv("AUTH_COOKIE_SECURE", "false").strip().lower() == "true"
)

AUTH_COOKIE_SAMESITE = (
    os.getenv("AUTH_COOKIE_SAMESITE", "lax").strip().lower()
)

if AUTH_COOKIE_SAMESITE not in {"lax", "strict"}:
    raise RuntimeError(
        "AUTH_COOKIE_SAMESITE must be either 'lax' or 'strict'"
    )

AUTH_COOKIE_NAME = (
    "__Host-jobhunter_session"
    if AUTH_COOKIE_SECURE
    else "jobhunter_session"
)