from __future__ import annotations

import secrets
import sqlite3
from datetime import datetime, timezone
from typing import Optional

from core import database

from .session import (
    consume_password_reset_token,
    create_password_reset_token,
    find_user_id_for_reset_token,
    invalidate_all_sessions_for_user,
    issue_access_token,
    revoke_token,
)


def find_user_by_email(
    email: str,
) -> sqlite3.Row | None:
    conn = database.get_db()

    try:
        return conn.execute(
            """
            SELECT
                id,
                email,
                name,
                password_hash,
                is_active
            FROM users
            WHERE email = ?
            LIMIT 1
            """,
            (email,),
        ).fetchone()
    finally:
        conn.close()


def create_session_for_user(
    user_id: str,
) -> str:
    conn = database.get_db()

    try:
        token = issue_access_token(
            conn,
            user_id,
        )

        now = datetime.now(
            timezone.utc
        ).isoformat()

        conn.execute(
            """
            UPDATE users
            SET
                last_login_at = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                now,
                now,
                user_id,
            ),
        )

        conn.commit()
        return token
    finally:
        conn.close()


def revoke_session(
    token: str,
) -> None:
    conn = database.get_db()

    try:
        revoke_token(
            conn,
            token,
        )
        conn.commit()
    finally:
        conn.close()


def create_user(
    email: str,
    password_hash: str,
    name: Optional[str],
) -> str:
    """
    Raises sqlite3.IntegrityError if the email already exists (users.email
    is UNIQUE) — the service layer is responsible for translating that into
    a clean 409 response.
    """
    conn = database.get_db()

    try:
        user_id = secrets.token_hex(16)
        now = datetime.now(timezone.utc).isoformat()

        conn.execute(
            """
            INSERT INTO users (
                id,
                email,
                name,
                password_hash,
                is_active,
                created_at,
                updated_at,
                last_login_at
            )
            VALUES (?, ?, ?, ?, 1, ?, ?, NULL)
            """,
            (
                user_id,
                email,
                name,
                password_hash,
                now,
                now,
            ),
        )

        conn.commit()
        return user_id
    finally:
        conn.close()


def issue_password_reset_token_for_email(
    email: str,
) -> Optional[tuple[str, str]]:
    """
    Returns (user_id, raw_token) if an active account exists for the email,
    otherwise None. The service layer must respond identically either way
    to avoid account enumeration — this function only returns the
    information needed to send an email; it never signals existence via
    exceptions or distinguishable return shapes beyond the Optional.
    """
    conn = database.get_db()

    try:
        row = conn.execute(
            """
            SELECT id, is_active
            FROM users
            WHERE email = ?
            LIMIT 1
            """,
            (email,),
        ).fetchone()

        if not row or not row["is_active"]:
            return None

        raw_token = create_password_reset_token(conn, row["id"])
        conn.commit()
        return row["id"], raw_token
    finally:
        conn.close()


def reset_password_with_token(
    token: str,
    new_password_hash: str,
) -> bool:
    """
    Validates the reset token, updates the password, consumes the token,
    and invalidates every existing session for that user — all in one
    transaction. Returns False if the token is missing, expired, or
    already used.
    """
    conn = database.get_db()

    try:
        user_id = find_user_id_for_reset_token(conn, token)

        if not user_id:
            return False

        now = datetime.now(timezone.utc).isoformat()

        conn.execute(
            """
            UPDATE users
            SET
                password_hash = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                new_password_hash,
                now,
                user_id,
            ),
        )

        consume_password_reset_token(conn, token)
        invalidate_all_sessions_for_user(conn, user_id)

        conn.commit()
        return True
    finally:
        conn.close()