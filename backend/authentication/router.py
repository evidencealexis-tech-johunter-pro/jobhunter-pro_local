from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response

from .schemas import (
    LoginRequest,
    PasswordResetConfirm,
    PasswordResetRequest,
    SignupRequest,
)
from .service import (
    authenticate,
    confirm_password_reset,
    logout,
    request_password_reset,
    signup,
)
from .session import (
    AUTH_COOKIE_NAME,
    CSRF_HEADER_NAME,
    clear_auth_cookie,
    csrf_token_for_session,
    get_request_session_token,
    set_auth_cookie,
)

router = APIRouter()


@router.post(
    "/api/apps/local/auth/login"
)
async def login_route(
    body: LoginRequest,
    response: Response,
):
    result = authenticate(body)

    set_auth_cookie(
        response,
        result["access_token"],
    )

    return result


@router.post(
    "/api/apps/local/auth/signup"
)
async def signup_route(
    body: SignupRequest,
    response: Response,
):
    result = signup(body)

    set_auth_cookie(
        response,
        result["access_token"],
    )

    return result


@router.post(
    "/api/apps/local/auth/password-reset/request"
)
async def password_reset_request_route(
    body: PasswordResetRequest,
):
    request_password_reset(body)

    # Same message every time — see the anti-enumeration note in
    # authentication/service.py::request_password_reset.
    return {
        "message": (
            "If an account exists for that email, "
            "a reset link has been sent."
        ),
    }


@router.post(
    "/api/apps/local/auth/password-reset/confirm"
)
async def password_reset_confirm_route(
    body: PasswordResetConfirm,
):
    confirm_password_reset(body)

    return {
        "message": (
            "Your password has been reset. "
            "Please log in with your new password."
        ),
    }


@router.post(
    "/api/apps/auth/logout"
)
async def logout_route(
    request: Request,
    response: Response,
):
    transport = get_request_session_token(
        request
    )

    if transport:
        token, _from_cookie = transport
        logout(token)

    clear_auth_cookie(response)

    return {
        "message": "Logged out successfully",
    }


@router.get(
    "/api/apps/local/auth/csrf"
)
async def get_csrf_token(
    request: Request,
):
    session_token = request.cookies.get(
        AUTH_COOKIE_NAME
    )

    if not session_token:
        raise HTTPException(
            status_code=401,
            detail="Cookie authentication required",
        )

    return {
        "csrf_token": csrf_token_for_session(
            session_token
        ),
        "header_name": CSRF_HEADER_NAME,
    }