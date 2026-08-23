from __future__ import annotations

import asyncio
import hmac
import socket
from contextlib import asynccontextmanager

import litellm
from llm import service as llm_service
from llm.schemas import InvokeLLMRequest
from llm.service import invoke_llm
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response as StarletteResponse

from authentication import (
    AUTH_COOKIE_NAME,
    CSRF_HEADER_NAME,
    SAFE_METHODS,
    CurrentUser,
    CurrentUserDep,
    csrf_token_for_session,
    ensure_auth_schema,
)
from authentication.router import router as authentication_router
from core.config import (
    ALLOWED_CORS_ORIGINS,
    APP_DEBUG,
)
from core.database import (
    get_db,
    mark_running_jobs_interrupted,
)
from file_storage import initialize_schema
from jobs.router import router as jobs_router
from entities.router import router as entities_router
from notifications.router import router as notifications_router
from settings.router import router as settings_router
from settings.service import (
    get_active_llm_credentials as settings_get_active_llm_credentials,
)
from uploads.router import router as uploads_router


def call_llm_with_retry(
    system_prompt: str = "",
    user_prompt: str = "",
    max_retries: int = 3,
    model: str | None = None,
    user_id: str | None = None,
):
    return llm_service.call_llm_with_retry(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        max_retries=max_retries,
        model=model,
        user_id=user_id,
        credentials_resolver=get_active_llm_credentials,
    )


async def call_llm_with_retry_async(
    system_prompt: str = "",
    user_prompt: str = "",
    max_retries: int = 3,
    model: str | None = None,
    user_id: str | None = None,
):
    return await llm_service.call_llm_with_retry_async(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        max_retries=max_retries,
        model=model,
        user_id=user_id,
        credentials_resolver=get_active_llm_credentials,
    )


# ============================================================================
# APPLICATION LIFECYCLE
# ============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    conn = get_db()

    try:
        initialize_schema(conn)
        ensure_auth_schema(conn)
        mark_running_jobs_interrupted(conn)
        conn.commit()
    finally:
        conn.close()

    yield


app = FastAPI(
    lifespan=lifespan,
    title="JobHunter Pro API",
)


if APP_DEBUG:
    litellm._turn_on_debug()


# ============================================================================
# ROUTERS
# ============================================================================

app.include_router(authentication_router)
app.include_router(jobs_router)
app.include_router(entities_router)
app.include_router(notifications_router)
app.include_router(settings_router)
app.include_router(uploads_router)


# ============================================================================
# CORS
# ============================================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(ALLOWED_CORS_ORIGINS),
    allow_credentials=True,
    allow_methods=[
        "GET",
        "HEAD",
        "POST",
        "PUT",
        "PATCH",
        "DELETE",
        "OPTIONS",
    ],
    allow_headers=[
        "Content-Type",
        "Authorization",
        CSRF_HEADER_NAME,
    ],
)


# ============================================================================
# BROWSER SESSION SECURITY
# ============================================================================

# These endpoints establish or change authentication state before the
# browser has a trusted authenticated session. They still pass the
# cross-site and Origin protections below, but do not require a CSRF
# token derived from an existing session cookie.
CSRF_EXEMPT_PATHS = {
    "/api/apps/local/auth/login",
    "/api/apps/local/auth/signup",
    "/api/apps/local/auth/password-reset/request",
    "/api/apps/local/auth/password-reset/confirm",
}


class BrowserSessionSecurityMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next,
    ):
        method = request.method.upper()
        cookie_token = request.cookies.get(
            AUTH_COOKIE_NAME
        )

        authorization = request.headers.get(
            "Authorization",
            "",
        )

        has_bearer_auth = authorization.lower().startswith(
            "bearer "
        )

        if (
            cookie_token
            and not has_bearer_auth
            and method not in SAFE_METHODS
        ):
            if request.headers.get(
                "Sec-Fetch-Site"
            ) == "cross-site":
                return StarletteResponse(
                    content='{"detail":"Cross-site request blocked"}',
                    status_code=403,
                    media_type="application/json",
                )

            origin = request.headers.get("Origin")

            if (
                origin
                and origin.rstrip("/") not in ALLOWED_CORS_ORIGINS
            ):
                return StarletteResponse(
                    content='{"detail":"Untrusted request origin"}',
                    status_code=403,
                    media_type="application/json",
                )

            # Authentication bootstrap/password-recovery endpoints
            # cannot safely require a CSRF token tied to an existing
            # authenticated session. Keep the origin protections above,
            # but skip the session-token CSRF comparison for these paths.
            if request.url.path not in CSRF_EXEMPT_PATHS:
                supplied = request.headers.get(
                    CSRF_HEADER_NAME,
                    "",
                )

                expected = csrf_token_for_session(
                    cookie_token
                )

                if (
                    not supplied
                    or not hmac.compare_digest(
                        supplied,
                        expected,
                    )
                ):
                    return StarletteResponse(
                        content='{"detail":"CSRF validation failed"}',
                        status_code=403,
                        media_type="application/json",
                    )

        response = await call_next(request)

        response.headers.setdefault(
            "X-Content-Type-Options",
            "nosniff",
        )

        response.headers.setdefault(
            "X-Frame-Options",
            "DENY",
        )

        response.headers.setdefault(
            "Referrer-Policy",
            "strict-origin-when-cross-origin",
        )

        response.headers.setdefault(
            "Permissions-Policy",
            "camera=(), microphone=(), geolocation=()",
        )

        if request.url.scheme == "https":
            response.headers.setdefault(
                "Strict-Transport-Security",
                "max-age=31536000; includeSubDomains",
            )

        return response


app.add_middleware(
    BrowserSessionSecurityMiddleware
)


# ============================================================================
# NETWORK STATUS
# ============================================================================

def has_internet_access(
    timeout: float = 2.0,
) -> bool:
    sock = socket.socket(
        socket.AF_INET,
        socket.SOCK_STREAM,
    )

    sock.settimeout(timeout)

    try:
        sock.connect(
            (
                "8.8.8.8",
                53,
            )
        )
        return True
    except OSError:
        return False
    finally:
        sock.close()


@app.get("/api/network-status")
async def network_status():
    return {
        "online": await asyncio.to_thread(
            has_internet_access
        )
    }


# ============================================================================
# LLM COMPATIBILITY BOUNDARY
# ============================================================================

def get_active_llm_credentials(
    user_id: str,
):
    return settings_get_active_llm_credentials(user_id)


@app.post(
    "/api/apps/local/integration-endpoints/Core/InvokeLLM"
)
async def invoke_llm_route(
    body: InvokeLLMRequest,
    current_user: CurrentUser = CurrentUserDep,
):
    return await invoke_llm(
        prompt=body.prompt,
        response_json_schema=body.response_json_schema,
        file_urls=body.file_urls,
        user_id=current_user.id,
        credentials_resolver=get_active_llm_credentials,
    )


# ============================================================================
# SMALL APPLICATION ENDPOINTS
# ============================================================================

@app.post(
    "/api/apps/local/analytics/track/batch"
)
async def track_analytics():
    return {
        "status": "ok",
    }


@app.get(
    "/api/apps/local/entities/User/me"
)
async def get_user(
    current_user: CurrentUser = CurrentUserDep,
):
    return {
        "id": current_user.id,
        "email": current_user.email,
        "name": current_user.name,
        "is_active": current_user.is_active,
    }


@app.get(
    "/api/apps/public/prod/public-settings/by-id/local"
)
async def get_settings():
    return {
        "settings": {},
    }