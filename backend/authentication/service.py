from __future__ import annotations

import sqlite3

from fastapi import HTTPException, status

from core.email import get_email_sender

from .repository import (
    create_session_for_user,
    create_user,
    find_user_by_email,
    issue_password_reset_token_for_email,
    reset_password_with_token,
    revoke_session,
)
from .schemas import (
    LoginRequest,
    PasswordResetConfirm,
    PasswordResetRequest,
    SignupRequest,
)
from .session import (
    PASSWORD_RESET_TOKEN_TTL_MINUTES,
    hash_password,
    is_plausible_email,
    normalize_email,
    validate_password_strength,
    verify_password,
)


def authenticate(
    body: LoginRequest,
) -> dict:
    email = normalize_email(
        body.email
    )

    if not email or not body.password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    user = find_user_by_email(
        email
    )

    if not user or not verify_password(
        body.password,
        user["password_hash"],
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if not user["is_active"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is disabled",
        )

    token = create_session_for_user(
        user["id"]
    )

    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": user["id"],
            "email": user["email"],
            "name": user["name"],
        },
    }


def logout(
    token: str | None,
) -> None:
    if token:
        revoke_session(token)


def signup(
    body: SignupRequest,
) -> dict:
    email = normalize_email(body.email)

    if not is_plausible_email(email):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid email address",
        )

    try:
        validate_password_strength(body.password)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    password_hash = hash_password(body.password)

    try:
        user_id = create_user(email, password_hash, body.name)
    except sqlite3.IntegrityError:
        # Signup duplicate-email disclosure is a deliberate, common
        # tradeoff (unlike password-reset-request below): the account's
        # existence is already discoverable via the login endpoint's
        # behavior, and hiding it here only costs UX without closing
        # off enumeration.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists",
        )

    token = create_session_for_user(user_id)

    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": user_id,
            "email": email,
            "name": body.name,
        },
    }


def request_password_reset(
    body: PasswordResetRequest,
) -> None:
    """
    Always completes with the same observable behavior regardless of
    whether the email belongs to an account, per the OWASP Forgot
    Password Cheat Sheet's anti-enumeration guidance. The router must
    return the same generic message on every call to this function —
    never branch the HTTP response on whether an email was actually
    sent.
    """
    email = normalize_email(body.email)
    result = issue_password_reset_token_for_email(email)

    if result:
        _user_id, raw_token = result
        sender = get_email_sender()
        sender.send(
            to=email,
            subject="Reset your JobHunter Pro password",
            body=(
                "A password reset was requested for this account.\n\n"
                f"Reset token: {raw_token}\n\n"
                f"This token expires in {PASSWORD_RESET_TOKEN_TTL_MINUTES} "
                "minutes and can only be used once. If you did not "
                "request this, you can safely ignore this email."
            ),
        )


def confirm_password_reset(
    body: PasswordResetConfirm,
) -> None:
    try:
        validate_password_strength(body.password)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    new_hash = hash_password(body.password)
    succeeded = reset_password_with_token(body.token, new_hash)

    if not succeeded:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token",
        )