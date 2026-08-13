import hashlib
import hmac
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, Request, status


ACCESS_TOKEN_TTL_MINUTES = 30


@dataclass(frozen=True)
class CurrentUser:
    id: str
    email: str
    name: Optional[str]
    is_active: bool


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _hash_password(password: str, salt: bytes, *, n: int = 16384, r: int = 8, p: int = 1) -> str:
    """
    Password hashing using Python's built-in scrypt.

    We store the parameters alongside the encoded hash so they can be
    changed deliberately later without losing the ability to verify
    existing passwords.
    """
    derived = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=n,
        r=r,
        p=p,
        dklen=32,
    )
    return f"scrypt$n={n},r={r},p={p}${salt.hex()}${derived.hex()}"


def hash_password(password: str) -> str:
    if not password:
        raise ValueError("Password cannot be empty")

    salt = secrets.token_bytes(16)
    return _hash_password(password, salt)


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        algorithm, params, salt_hex, digest_hex = stored_hash.split("$", 3)
        if algorithm != "scrypt":
            return False

        values = {}
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
    except (ValueError, KeyError):
        return False


def normalize_email(email: str) -> str:
    return email.strip().lower()


def issue_access_token(conn: sqlite3.Connection, user_id: str) -> str:
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


def revoke_token(conn: sqlite3.Connection, token: str) -> None:
    conn.execute(
        """
        UPDATE auth_sessions
        SET revoked_at = ?
        WHERE token_hash = ?
        """,
        (utc_now().isoformat(), _hash_token(token)),
    )


def _bearer_token(request: Request) -> str:
    header = request.headers.get("Authorization", "")

    if not header:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    scheme, _, token = header.partition(" ")

    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return token.strip()


def get_current_user(request: Request) -> CurrentUser:
    token = _bearer_token(request)

    # Import lazily to avoid circular import:
    # main.py owns get_db(), while auth.py owns auth behavior.
    from main import get_db

    conn = get_db()
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
            (_hash_token(token), utc_now().isoformat()),
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