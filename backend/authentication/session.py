from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, Request, Response, status

from core import database

from .models import CurrentUser


ACCESS_TOKEN_TTL_MINUTES = 30
AUTH_COOKIE_MAX_AGE = ACCESS_TOKEN_TTL_MINUTES * 60
AUTH_COOKIE_SECURE = os.getenv("AUTH_COOKIE_SECURE", "false").lower() == "true"
AUTH_COOKIE_SAMESITE = os.getenv("AUTH_COOKIE_SAMESITE", "lax").lower()

# Per OWASP Forgot Password Cheat Sheet: short-lived, single-use reset tokens.
PASSWORD_RESET_TOKEN_TTL_MINUTES = 30

# Per NIST SP800-63B: enforce a floor on length, not composition rules.
# Upper bound guards against hashing-cost abuse (very long inputs into scrypt).
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 128

_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

if AUTH_COOKIE_SAMESITE not in {"lax", "strict"}:
    raise RuntimeError(
        "AUTH_COOKIE_SAMESITE must be either 'lax' or 'strict'"
    )

AUTH_COOKIE_NAME = (
    "__Host-jobhunter_session"
    if AUTH_COOKIE_SECURE
    else "jobhunter_session"
)

CSRF_HEADER_NAME = "X-CSRF-Token"
CSRF_CONTEXT = b"jobhunter-pro-csrf-v1"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _hash_password(
    password: str,
    salt: bytes,
    *,
    n: int = 16384,
    r: int = 8,
    p: int = 1,
) -> str:
    """
    Password hashing using Python's built-in scrypt.

    The encoded format stores the work-factor parameters alongside the hash
    so existing passwords can continue to be verified if the parameters are
    increased in a later migration.
    """
    derived = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=n,
        r=r,
        p=p,
        dklen=32,
    )

    return (
        f"scrypt$n={n},r={r},p={p}"
        f"${salt.hex()}"
        f"${derived.hex()}"
    )


def hash_password(password: str) -> str:
    if not password:
        raise ValueError("Password cannot be empty")

    salt = secrets.token_bytes(16)
    return _hash_password(password, salt)


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        algorithm, params, salt_hex, _digest_hex = stored_hash.split("$", 3)

        if algorithm != "scrypt":
            return False

        values: dict[str, int] = {}

        for part in params.split(","):
            key, value = part.split("=", 1)
            values[key] = int(value)

        expected = _hash_password(
            password,
            bytes.fromhex(salt_hex),
            n=values["n"],
            r=values["r"],
            p=values["p"],
        )

        return hmac.compare_digest(expected, stored_hash)
    except (ValueError, KeyError, TypeError):
        return False


def normalize_email(email: str) -> str:
    return email.strip().lower()


def is_plausible_email(email: str) -> bool:
    """
    Cheap sanity check only — real deliverability is confirmed by the
    reset/confirmation email actually landing, not by regex.
    """
    return bool(email) and bool(_EMAIL_PATTERN.match(email)) and len(email) <= 254


def validate_password_strength(password: str) -> None:
    """
    Raises ValueError with a user-facing message on failure.

    Deliberately does NOT enforce composition rules (uppercase/digit/symbol
    quotas) per NIST SP800-63B guidance — length is the meaningful signal.
    """
    if not password or len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(
            f"Password must be at least {MIN_PASSWORD_LENGTH} characters"
        )

    if len(password) > MAX_PASSWORD_LENGTH:
        raise ValueError(
            f"Password must be at most {MAX_PASSWORD_LENGTH} characters"
        )


def issue_access_token(
    conn: sqlite3.Connection,
    user_id: str,
) -> str:
    raw_token = secrets.token_urlsafe(48)
    token_hash = _hash_token(raw_token)

    now = utc_now()
    expires = now + timedelta(minutes=ACCESS_TOKEN_TTL_MINUTES)
    session_id = secrets.token_hex(16)

    conn.execute(
        """
        INSERT INTO auth_sessions (
            id,
            user_id,
            token_hash,
            created_at,
            expires_at,
            revoked_at
        )
        VALUES (?, ?, ?, ?, ?, NULL)
        """,
        (
            session_id,
            user_id,
            token_hash,
            now.isoformat(),
            expires.isoformat(),
        ),
    )

    return raw_token


def revoke_token(
    conn: sqlite3.Connection,
    token: str,
) -> None:
    conn.execute(
        """
        UPDATE auth_sessions
        SET revoked_at = ?
        WHERE token_hash = ?
        """,
        (
            utc_now().isoformat(),
            _hash_token(token),
        ),
    )


def invalidate_all_sessions_for_user(
    conn: sqlite3.Connection,
    user_id: str,
) -> None:
    """
    Called after a password change/reset. Every existing session token
    (bearer or cookie) becomes invalid immediately, per OWASP guidance that
    a credential change must not leave prior sessions live.
    """
    conn.execute(
        """
        UPDATE auth_sessions
        SET revoked_at = ?
        WHERE user_id = ?
          AND revoked_at IS NULL
        """,
        (
            utc_now().isoformat(),
            user_id,
        ),
    )


def create_password_reset_token(
    conn: sqlite3.Connection,
    user_id: str,
) -> str:
    raw_token = secrets.token_urlsafe(48)
    token_hash = _hash_token(raw_token)

    now = utc_now()
    expires = now + timedelta(minutes=PASSWORD_RESET_TOKEN_TTL_MINUTES)
    token_id = secrets.token_hex(16)

    conn.execute(
        """
        INSERT INTO password_reset_tokens (
            id,
            user_id,
            token_hash,
            created_at,
            expires_at,
            used_at
        )
        VALUES (?, ?, ?, ?, ?, NULL)
        """,
        (
            token_id,
            user_id,
            token_hash,
            now.isoformat(),
            expires.isoformat(),
        ),
    )

    return raw_token


def find_user_id_for_reset_token(
    conn: sqlite3.Connection,
    token: str,
) -> Optional[str]:
    row = conn.execute(
        """
        SELECT user_id
        FROM password_reset_tokens
        WHERE token_hash = ?
          AND used_at IS NULL
          AND expires_at > ?
        LIMIT 1
        """,
        (
            _hash_token(token),
            utc_now().isoformat(),
        ),
    ).fetchone()

    return row["user_id"] if row else None


def consume_password_reset_token(
    conn: sqlite3.Connection,
    token: str,
) -> None:
    conn.execute(
        """
        UPDATE password_reset_tokens
        SET used_at = ?
        WHERE token_hash = ?
        """,
        (
            utc_now().isoformat(),
            _hash_token(token),
        ),
    )


def ensure_auth_schema(conn: sqlite3.Connection) -> None:
    """
    Idempotent schema setup for tables owned by the authentication package.

    `users` and `auth_sessions` are created by the application's main schema
    initialization (they predate this module). `password_reset_tokens` is
    new as of the signup/password-reset extraction and is created here so
    the authentication package owns its own schema going forward. Call this
    once at startup, after the main schema init, and before serving traffic.
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS password_reset_tokens (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            token_hash TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            used_at TEXT,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
        """
    )

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_password_reset_tokens_token_hash
        ON password_reset_tokens(token_hash)
        """
    )

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_password_reset_tokens_user_id
        ON password_reset_tokens(user_id)
        """
    )

    conn.commit()


def csrf_token_for_session(session_token: str) -> str:
    """
    Derive a per-session CSRF token from the session secret.

    The session secret is HttpOnly and therefore unavailable to browser
    JavaScript. The derived CSRF token can safely be exposed to the SPA and
    supplied in a custom header for state-changing requests.
    """
    return hmac.new(
        session_token.encode("utf-8"),
        CSRF_CONTEXT,
        hashlib.sha256,
    ).hexdigest()


def set_auth_cookie(
    response: Response,
    session_token: str,
) -> None:
    response.set_cookie(
        key=AUTH_COOKIE_NAME,
        value=session_token,
        max_age=AUTH_COOKIE_MAX_AGE,
        httponly=True,
        secure=AUTH_COOKIE_SECURE,
        samesite=AUTH_COOKIE_SAMESITE,
        path="/",
    )


def clear_auth_cookie(response: Response) -> None:
    response.delete_cookie(
        key=AUTH_COOKIE_NAME,
        path="/",
    )


def _extract_bearer_token(
    request: Request,
) -> Optional[str]:
    header = request.headers.get("Authorization", "")

    if not header:
        return None

    scheme, _, token = header.partition(" ")

    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return token.strip()


def _extract_auth_token(
    request: Request,
) -> tuple[str, bool]:
    """
    Return (session_token, came_from_cookie).
    """
    bearer_token = _extract_bearer_token(request)

    if bearer_token:
        return bearer_token, False

    cookie_token = request.cookies.get(AUTH_COOKIE_NAME)

    if cookie_token:
        return cookie_token, True

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required",
        headers={"WWW-Authenticate": "Bearer"},
    )


def enforce_csrf(
    request: Request,
    session_token: str,
    from_cookie: bool,
) -> None:
    """
    Protect cookie-authenticated state-changing requests against CSRF.
    """
    if not from_cookie or request.method.upper() in SAFE_METHODS:
        return

    supplied = request.headers.get(CSRF_HEADER_NAME, "")
    expected = csrf_token_for_session(session_token)

    if not supplied or not hmac.compare_digest(supplied, expected):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF validation failed",
        )


def get_request_session_token(
    request: Request,
) -> Optional[tuple[str, bool]]:
    """
    Return authenticated transport information without requiring auth.
    """
    bearer_token = _extract_bearer_token(request)

    if bearer_token:
        return bearer_token, False

    cookie_token = request.cookies.get(AUTH_COOKIE_NAME)

    if cookie_token:
        return cookie_token, True

    return None


def get_current_user(request: Request) -> CurrentUser:
    session_token, from_cookie = _extract_auth_token(request)
    enforce_csrf(request, session_token, from_cookie)

    conn = database.get_db()

    try:
        row = conn.execute(
            """
            SELECT
                u.id,
                u.email,
                u.name,
                u.is_active
            FROM auth_sessions s
            JOIN users u ON u.id = s.user_id
            WHERE s.token_hash = ?
              AND s.revoked_at IS NULL
              AND s.expires_at > ?
              AND u.is_active = 1
            LIMIT 1
            """,
            (
                _hash_token(session_token),
                utc_now().isoformat(),
            ),
        ).fetchone()

        if not row:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired authentication credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )

        return CurrentUser(
            id=row["id"],
            email=row["email"],
            name=row["name"],
            is_active=bool(row["is_active"]),
        )
    finally:
        conn.close()


CurrentUserDep = Depends(get_current_user)