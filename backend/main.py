from __future__ import annotations

import asyncio
import hmac
import json
import os
import socket
import time
import uuid
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from typing import Optional

import litellm
from fastapi import (
    Depends,
    FastAPI,
    File,
    HTTPException,
    Request,
    Response,
    UploadFile,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response as StarletteResponse

from auth import (
    AUTH_COOKIE_NAME,
    CSRF_HEADER_NAME,
    SAFE_METHODS,
    CurrentUser,
    CurrentUserDep,
    clear_auth_cookie,
    csrf_token_for_session,
    get_request_session_token,
    hash_password,
    issue_access_token,
    normalize_email,
    revoke_token,
    set_auth_cookie,
    verify_password,
)
from core.config import (
    ALLOWED_CORS_ORIGINS,
    APP_DEBUG,
    PREFILTER_ENABLED,
    RATE_LIMIT_SECONDS,
)
from core.database import (
    get_db,
    initialize_database,
    mark_running_jobs_interrupted,
)
from encryption import (
    decrypt_api_key,
    detect_provider_from_key,
    encrypt_api_key,
)
from file_storage import (
    MAX_UPLOAD_BYTES,
    file_reference,
    get_owned_file,
    initialize_schema,
    store_pdf,
)
from pdf_extraction import extract_text_from_pdf
from remote_config import load_config
from scraper import detect_and_fetch, normalize_job


@asynccontextmanager
async def lifespan(app: FastAPI):
    conn = get_db()
    try:
        initialize_database(conn)
        initialize_schema(conn)
        mark_running_jobs_interrupted(conn)
        conn.commit()
    finally:
        conn.close()

    yield


app = FastAPI(lifespan=lifespan)

if APP_DEBUG:
    litellm._turn_on_debug()


class LoginRequest(BaseModel):
    email: str
    password: str


@app.post("/api/apps/local/auth/login")
async def login(body: LoginRequest, response: Response):
    email = normalize_email(body.email)

    if not email or not body.password:
        raise HTTPException(
            status_code=401,
            detail="Invalid email or password",
        )

    conn = get_db()

    try:
        user = conn.execute(
            """
            SELECT id, email, name, password_hash, is_active
            FROM users
            WHERE email = ?
            LIMIT 1
            """,
            (email,),
        ).fetchone()

        if not user or not verify_password(
            body.password,
            user["password_hash"],
        ):
            raise HTTPException(
                status_code=401,
                detail="Invalid email or password",
            )

        if not user["is_active"]:
            raise HTTPException(
                status_code=403,
                detail="Account is disabled",
            )

        now = datetime.now(timezone.utc).isoformat()
        token = issue_access_token(conn, user["id"])

        conn.execute(
            """
            UPDATE users
            SET last_login_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                now,
                now,
                user["id"],
            ),
        )

        conn.commit()
        set_auth_cookie(response, token)

        return {
            "access_token": token,
            "token_type": "bearer",
            "user": {
                "id": user["id"],
                "email": user["email"],
                "name": user["name"],
            },
        }
    finally:
        conn.close()


@app.post("/api/apps/auth/logout")
async def logout(
    request: Request,
    response: Response,
):
    transport = get_request_session_token(request)

    if transport:
        token, _from_cookie = transport
        conn = get_db()

        try:
            revoke_token(conn, token)
            conn.commit()
        finally:
            conn.close()

    clear_auth_cookie(response)

    return {
        "message": "Logged out successfully",
    }


@app.get("/api/apps/local/auth/csrf")
async def get_csrf_token(request: Request):
    session_token = request.cookies.get(AUTH_COOKIE_NAME)

    if not session_token:
        raise HTTPException(
            status_code=401,
            detail="Cookie authentication required",
        )

    return {
        "csrf_token": csrf_token_for_session(session_token),
        "header_name": CSRF_HEADER_NAME,
    }


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


class BrowserSessionSecurityMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next,
    ):
        method = request.method.upper()
        cookie_token = request.cookies.get(AUTH_COOKIE_NAME)
        authorization = request.headers.get("Authorization", "")
        has_bearer_auth = authorization.lower().startswith("bearer ")

        if (
            cookie_token
            and not has_bearer_auth
            and method not in SAFE_METHODS
        ):
            if request.headers.get("Sec-Fetch-Site") == "cross-site":
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

            supplied = request.headers.get(
                CSRF_HEADER_NAME,
                "",
            )
            expected = csrf_token_for_session(cookie_token)

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


app.add_middleware(BrowserSessionSecurityMiddleware)


background_tasks = set()

VALID_ENTITIES = {
    "Resume",
    "Job",
    "ScrapeSource",
    "ContextDocument",
    "AppSettings",
    "UserApiKey",
    "ScrapeJob",
    "Notification",
}


def _validate_entity(entity_name: str) -> str:
    if entity_name not in VALID_ENTITIES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid entity: {entity_name}",
        )

    if entity_name in {
        "UserApiKey",
        "Notification",
    }:
        raise HTTPException(
            status_code=403,
            detail=(
                f"{entity_name} is managed through "
                "authenticated endpoints"
            ),
        )

    return entity_name


def _friendly_provider_error(
    error: Exception,
    provider: str | None = None,
) -> str:
    message = str(error).lower()

    if (
        "incorrect api key" in message
        or "api key not valid" in message
        or "authentication" in message
        or "401" in message
    ):
        base = "Invalid API key"
    elif "403" in message or "permission" in message:
        base = (
            "That key does not have permission to use this model"
        )
    elif "404" in message or "not found" in message:
        base = "Provider endpoint not found"
    elif "405" in message or "method not allowed" in message:
        base = "Provider rejected the request"
    elif (
        "429" in message
        or "rate limit" in message
        or "resource_exhausted" in message
    ):
        base = "Rate limit hit"
    elif (
        "insufficient balance" in message
        or "quota" in message
        or "billing" in message
    ):
        base = (
            "Your account has no credits or has hit its "
            "spending limit"
        )
    elif (
        "timeout" in message
        or "connection" in message
    ):
        base = "Could not reach the provider"
    else:
        base = "That key was rejected"

    if provider:
        return (
            f"{base} by {provider}. "
            "Please verify your provider, model, and key."
        )

    return (
        f"{base}. "
        "Please verify your provider, model, and key."
    )


@app.get("/api/apps/local/entities/{entity_name}")
async def get_entities(
    entity_name: str,
    q: Optional[str] = None,
    sort: Optional[str] = None,
    limit: Optional[int] = None,
    current_user: CurrentUser = CurrentUserDep,
):
    _validate_entity(entity_name)

    conn = get_db()

    try:
        if entity_name in {
            "Resume",
            "Job",
        }:
            cursor = conn.execute(
                f"""
                SELECT data
                FROM {entity_name}
                WHERE json_extract(
                    data,
                    '$.user_id'
                ) = ?
                """,
                (current_user.id,),
            )
        else:
            cursor = conn.execute(
                f"SELECT data FROM {entity_name}"
            )

        rows = cursor.fetchall()
    finally:
        conn.close()

    items = [
        json.loads(row["data"])
        for row in rows
    ]

    if q:
        try:
            filters = json.loads(q)

            if not isinstance(filters, dict):
                raise HTTPException(
                    status_code=400,
                    detail="Filter must be a JSON object",
                )

            items = [
                item
                for item in items
                if all(
                    item.get(key) == value
                    for key, value in filters.items()
                )
            ]
        except json.JSONDecodeError as exc:
            raise HTTPException(
                status_code=400,
                detail="Invalid JSON in filter",
            ) from exc

    if sort:
        descending = sort.startswith("-")
        field = sort[1:] if descending else sort

        items.sort(
            key=lambda item: str(
                item.get(field) or ""
            ),
            reverse=descending,
        )

    if limit is not None:
        items = items[:limit]

    return items


class EntityPayload(BaseModel):
    model_config = {
        "extra": "allow",
    }


@app.post("/api/apps/local/entities/{entity_name}")
async def post_entities(
    entity_name: str,
    body: EntityPayload,
    current_user: CurrentUser = CurrentUserDep,
):
    _validate_entity(entity_name)

    data = body.model_dump()

    item_id = data.get("id") or str(uuid.uuid4())
    data["id"] = item_id

    if "created_date" not in data:
        data["created_date"] = date.today().isoformat()

    if entity_name in {
        "Resume",
        "Job",
    }:
        data["user_id"] = current_user.id

    conn = get_db()

    try:
        if (
            entity_name == "Resume"
            and data.get("active") is True
        ):
            conn.execute(
                """
                UPDATE Resume
                SET data = json_set(
                    data,
                    '$.active',
                    json('false')
                )
                WHERE json_extract(
                    data,
                    '$.user_id'
                ) = ?
                """,
                (current_user.id,),
            )

        conn.execute(
            f"""
            INSERT OR REPLACE INTO {entity_name}
            (id, data)
            VALUES (?, ?)
            """,
            (
                item_id,
                json.dumps(data),
            ),
        )

        conn.commit()
    finally:
        conn.close()

    return data


@app.put(
    "/api/apps/local/entities/{entity_name}/{item_id}"
)
@app.patch(
    "/api/apps/local/entities/{entity_name}/{item_id}"
)
async def update_entity(
    entity_name: str,
    item_id: str,
    body: EntityPayload,
    current_user: CurrentUser = CurrentUserDep,
):
    _validate_entity(entity_name)

    updates = body.model_dump()
    conn = get_db()

    try:
        if entity_name in {
            "Resume",
            "Job",
        }:
            cursor = conn.execute(
                f"""
                SELECT data
                FROM {entity_name}
                WHERE id = ?
                  AND json_extract(
                      data,
                      '$.user_id'
                  ) = ?
                """,
                (
                    item_id,
                    current_user.id,
                ),
            )
        else:
            cursor = conn.execute(
                f"""
                SELECT data
                FROM {entity_name}
                WHERE id = ?
                """,
                (item_id,),
            )

        row = cursor.fetchone()

        if not row:
            raise HTTPException(
                status_code=404,
                detail="Item not found",
            )

        existing = json.loads(row["data"])

        if entity_name in {
            "Resume",
            "Job",
        }:
            updates.pop("user_id", None)
            existing["user_id"] = current_user.id

        existing.update(updates)
        existing["id"] = item_id

        if (
            entity_name == "Resume"
            and existing.get("active") is True
        ):
            conn.execute(
                """
                UPDATE Resume
                SET data = json_set(
                    data,
                    '$.active',
                    json('false')
                )
                WHERE json_extract(
                    data,
                    '$.user_id'
                ) = ?
                  AND id != ?
                """,
                (
                    current_user.id,
                    item_id,
                ),
            )

        conn.execute(
            f"""
            UPDATE {entity_name}
            SET data = ?
            WHERE id = ?
            """,
            (
                json.dumps(existing),
                item_id,
            ),
        )

        conn.commit()

        return existing
    finally:
        conn.close()


@app.delete("/api/apps/local/entities/Job/clear-all")
async def clear_all_jobs(
    current_user: CurrentUser = CurrentUserDep,
):
    conn = get_db()

    try:
        conn.execute(
            """
            DELETE FROM Job
            WHERE json_extract(
                data,
                '$.user_id'
            ) = ?
            """,
            (current_user.id,),
        )

        conn.commit()
    finally:
        conn.close()

    return {
        "status": "success",
        "message": "All jobs cleared",
    }


@app.delete(
    "/api/apps/local/entities/{entity_name}/{item_id}"
)
async def delete_entity(
    entity_name: str,
    item_id: str,
    current_user: CurrentUser = CurrentUserDep,
):
    _validate_entity(entity_name)

    if item_id == "undefined":
        return {
            "status": "ignored",
        }

    conn = get_db()

    try:
        if entity_name in {
            "Resume",
            "Job",
        }:
            cursor = conn.execute(
                f"""
                DELETE FROM {entity_name}
                WHERE id = ?
                  AND json_extract(
                      data,
                      '$.user_id'
                  ) = ?
                """,
                (
                    item_id,
                    current_user.id,
                ),
            )
        else:
            cursor = conn.execute(
                f"""
                DELETE FROM {entity_name}
                WHERE id = ?
                """,
                (item_id,),
            )

        if (
            entity_name in {
                "Resume",
                "Job",
            }
            and cursor.rowcount == 0
        ):
            raise HTTPException(
                status_code=404,
                detail="Item not found",
            )

        conn.commit()
    finally:
        conn.close()

    return {
        "status": "deleted",
    }


@app.delete(
    "/api/apps/local/entities/{entity_name}"
)
async def delete_entity_by_query(
    entity_name: str,
    id: str,
    current_user: CurrentUser = CurrentUserDep,
):
    _validate_entity(entity_name)

    if id == "undefined":
        return {
            "status": "ignored",
        }

    conn = get_db()

    try:
        if entity_name in {
            "Resume",
            "Job",
        }:
            cursor = conn.execute(
                f"""
                DELETE FROM {entity_name}
                WHERE id = ?
                  AND json_extract(
                      data,
                      '$.user_id'
                  ) = ?
                """,
                (
                    id,
                    current_user.id,
                ),
            )
        else:
            cursor = conn.execute(
                f"""
                DELETE FROM {entity_name}
                WHERE id = ?
                """,
                (id,),
            )

        if (
            entity_name in {
                "Resume",
                "Job",
            }
            and cursor.rowcount == 0
        ):
            raise HTTPException(
                status_code=404,
                detail="Item not found",
            )

        conn.commit()
    finally:
        conn.close()

    return {
        "status": "deleted",
    }


def add_notification(
    message: str,
    user_id: str,
    type: str = "info",
    context: str | None = None,
):
    if not user_id:
        raise ValueError(
            "Notification owner is required"
        )

    conn = get_db()

    try:
        new_id = str(uuid.uuid4())

        notification = {
            "id": new_id,
            "user_id": user_id,
            "message": message,
            "type": type,
            "context": context,
            "read": False,
            "created_at": (
                datetime.now(
                    timezone.utc
                ).isoformat()
            ),
        }

        conn.execute(
            """
            INSERT INTO Notification
            (id, data)
            VALUES (?, ?)
            """,
            (
                new_id,
                json.dumps(notification),
            ),
        )

        conn.commit()
    finally:
        conn.close()


@app.get("/api/notifications")
async def get_notifications(
    limit: int = 50,
    current_user: CurrentUser = CurrentUserDep,
):
    limit = max(
        1,
        min(limit, 100),
    )

    conn = get_db()

    try:
        cursor = conn.execute(
            """
            SELECT data
            FROM Notification
            WHERE json_extract(
                data,
                '$.user_id'
            ) = ?
            """,
            (current_user.id,),
        )

        rows = cursor.fetchall()
    finally:
        conn.close()

    items = [
        json.loads(row["data"])
        for row in rows
    ]

    items.sort(
        key=lambda item: item.get(
            "created_at",
            "",
        ),
        reverse=True,
    )

    unread_count = sum(
        1
        for item in items
        if not item.get("read")
    )

    return {
        "notifications": items[:limit],
        "unread_count": unread_count,
    }


@app.post("/api/notifications/mark-all-read")
async def mark_all_notifications_read(
    current_user: CurrentUser = CurrentUserDep,
):
    conn = get_db()

    try:
        cursor = conn.execute(
            """
            SELECT data
            FROM Notification
            WHERE json_extract(
                data,
                '$.user_id'
            ) = ?
            """,
            (current_user.id,),
        )

        rows = cursor.fetchall()

        for row in rows:
            data = json.loads(row["data"])
            data["read"] = True

            conn.execute(
                """
                UPDATE Notification
                SET data = ?
                WHERE id = ?
                """,
                (
                    json.dumps(data),
                    data["id"],
                ),
            )

        conn.commit()
    finally:
        conn.close()

    return {
        "status": "success",
    }


@app.delete("/api/notifications")
async def clear_notifications(
    current_user: CurrentUser = CurrentUserDep,
):
    conn = get_db()

    try:
        conn.execute(
            """
            DELETE FROM Notification
            WHERE json_extract(
                data,
                '$.user_id'
            ) = ?
            """,
            (current_user.id,),
        )

        conn.commit()
    finally:
        conn.close()

    return {
        "status": "success",
    }


def has_internet_access(
    timeout: float = 2.0,
) -> bool:
    try:
        socket.setdefaulttimeout(timeout)

        sock = socket.socket(
            socket.AF_INET,
            socket.SOCK_STREAM,
        )

        try:
            sock.connect(
                (
                    "8.8.8.8",
                    53,
                )
            )
        finally:
            sock.close()

        return True
    except OSError:
        return False


@app.get("/api/network-status")
async def network_status():
    online = await asyncio.to_thread(
        has_internet_access
    )

    return {
        "online": online,
    }


@app.post(
    "/api/apps/local/integration-endpoints/Core/UploadFile"
)
async def upload_file(
    file: UploadFile = File(...),
    current_user: CurrentUser = CurrentUserDep,
):
    conn = get_db()

    try:
        content = await file.read(
            MAX_UPLOAD_BYTES + 1
        )

        stored = store_pdf(
            conn,
            user_id=current_user.id,
            filename=file.filename,
            content_type=file.content_type,
            content=content,
        )

        return {
            "file_id": stored.file_id,
            "file_url": file_reference(
                stored.file_id
            ),
            "filename": stored.original_filename,
            "stored_filename": os.path.basename(
                stored.storage_path
            ),
            "content_type": stored.content_type,
            "size_bytes": stored.size_bytes,
        }
    except HTTPException:
        raise
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail="Could not store uploaded file.",
        ) from exc
    finally:
        conn.close()


@app.get("/api/files/{file_id}")
async def download_uploaded_file(
    file_id: str,
    current_user: CurrentUser = CurrentUserDep,
):
    conn = get_db()

    try:
        stored_file = get_owned_file(
            conn,
            user_id=current_user.id,
            file_reference=file_reference(
                file_id
            ),
        )
    finally:
        conn.close()

    return FileResponse(
        path=stored_file.storage_path,
        media_type=stored_file.content_type,
        filename=stored_file.original_filename,
        headers={
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": (
                'attachment; filename="'
                f"{stored_file.original_filename}"
                '"'
            ),
        },
    )


class SaveApiKeyRequest(BaseModel):
    api_key: str
    provider: str | None = None
    model: str | None = None
    base_url: str | None = None
    label: str = "Default"


@app.post("/api/settings/api-key")
async def save_api_key(
    body: SaveApiKeyRequest,
    current_user: CurrentUser = CurrentUserDep,
):
    api_key = body.api_key.strip()
    provider = (
        body.provider.strip().lower()
        if body.provider
        else None
    )
    user_model = (
        body.model.strip()
        if body.model
        else None
    )
    base_url = (
        body.base_url.strip()
        if body.base_url
        else None
    )
    label = body.label

    if not api_key:
        raise HTTPException(
            status_code=400,
            detail="API key is required",
        )

    config = load_config()

    if provider == "custom":
        if not base_url:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Base URL is required "
                    "for a custom provider"
                ),
            )

        if not user_model:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Model name is required "
                    "for a custom provider"
                ),
            )

        try:
            litellm.completion(
                model=f"openai/{user_model}",
                api_base=base_url,
                api_key=api_key,
                messages=[
                    {
                        "role": "user",
                        "content": "test",
                    }
                ],
                max_tokens=1,
                timeout=10,
            )
        except Exception as exc:
            raise HTTPException(
                status_code=400,
                detail=_friendly_provider_error(
                    exc,
                    provider=provider,
                ),
            ) from exc

        _store_key(
            api_key,
            current_user.id,
            provider="custom",
            model=user_model,
            label=label,
            base_url=base_url,
        )

        return {
            "status": "success",
            "message": (
                "Custom provider key saved "
                "and activated"
            ),
        }

    if provider and provider != "auto":
        if provider not in config[
            "supported_providers"
        ]:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Unsupported provider: "
                    f"{provider}"
                ),
            )

        test_model = (
            user_model
            or config["default_models"].get(
                provider
            )
        )

        if not test_model:
            raise HTTPException(
                status_code=400,
                detail=(
                    "No default model configured "
                    f"for {provider}"
                ),
            )

        full_model = (
            test_model
            if "/" in test_model
            else f"{provider}/{test_model}"
        )

        try:
            litellm.completion(
                model=full_model,
                api_key=api_key,
                messages=[
                    {
                        "role": "user",
                        "content": "test",
                    }
                ],
                max_tokens=1,
                timeout=10,
            )
        except Exception as exc:
            raise HTTPException(
                status_code=400,
                detail=_friendly_provider_error(
                    exc,
                    provider=provider,
                ),
            ) from exc

        _store_key(
            api_key,
            current_user.id,
            provider=provider,
            model=user_model,
            label=label,
        )

        return {
            "status": "success",
            "message": (
                f"{provider} key saved "
                "and activated"
            ),
        }

    detected = detect_provider_from_key(
        api_key
    )

    if not detected:
        for candidate in config[
            "supported_providers"
        ]:
            if candidate == "custom":
                continue

            model = config[
                "default_models"
            ].get(candidate)

            if not model:
                continue

            try:
                litellm.completion(
                    model=model,
                    api_key=api_key,
                    messages=[
                        {
                            "role": "user",
                            "content": "test",
                        }
                    ],
                    max_tokens=1,
                    timeout=10,
                )

                detected = candidate
                break
            except Exception:
                continue

    if not detected:
        return {
            "status": "provider_required",
            "message": (
                "Couldn't determine which provider "
                "this key belongs to. Please select "
                "it manually."
            ),
            "providers": config["providers"],
        }

    _store_key(
        api_key,
        current_user.id,
        provider=detected,
        model=None,
        label=label,
    )

    return {
        "status": "success",
        "message": (
            f"Detected {detected} - "
            "key saved and activated"
        ),
    }


def _store_key(
    api_key,
    user_id,
    provider,
    model,
    label,
    base_url=None,
):
    encrypted = encrypt_api_key(api_key)
    key_suffix = (
        api_key[-4:]
        if len(api_key) >= 4
        else "****"
    )

    conn = get_db()

    try:
        cursor = conn.execute(
            """
            SELECT data
            FROM UserApiKey
            WHERE json_extract(
                data,
                '$.status'
            ) = 'active'
              AND json_extract(
                  data,
                  '$.user_id'
              ) = ?
            """,
            (user_id,),
        )

        for row in cursor.fetchall():
            existing = json.loads(
                row["data"]
            )

            existing["status"] = "revoked"

            conn.execute(
                """
                UPDATE UserApiKey
                SET data = ?
                WHERE id = ?
                """,
                (
                    json.dumps(existing),
                    existing["id"],
                ),
            )

        new_id = str(uuid.uuid4())

        new_key = {
            "id": new_id,
            "user_id": user_id,
            "provider": provider,
            "encrypted_key": encrypted,
            "key_suffix": key_suffix,
            "status": "active",
            "created_at": date.today().isoformat(),
            "label": label,
            "model": model,
        }

        if base_url:
            new_key["base_url"] = base_url

        conn.execute(
            """
            INSERT INTO UserApiKey
            (id, data)
            VALUES (?, ?)
            """,
            (
                new_id,
                json.dumps(new_key),
            ),
        )

        conn.commit()
    finally:
        conn.close()


@app.delete("/api/settings/api-key")
async def remove_api_key(
    current_user: CurrentUser = CurrentUserDep,
):
    conn = get_db()

    try:
        cursor = conn.execute(
            """
            SELECT data
            FROM UserApiKey
            WHERE json_extract(
                data,
                '$.status'
            ) = 'active'
              AND json_extract(
                  data,
                  '$.user_id'
              ) = ?
            """,
            (current_user.id,),
        )

        row = cursor.fetchone()

        if not row:
            raise HTTPException(
                status_code=404,
                detail="No active key to remove",
            )

        key_data = json.loads(
            row["data"]
        )
        key_data["status"] = "revoked"

        conn.execute(
            """
            UPDATE UserApiKey
            SET data = ?
            WHERE id = ?
            """,
            (
                json.dumps(key_data),
                key_data["id"],
            ),
        )

        conn.commit()
    finally:
        conn.close()

    return {
        "status": "success",
        "message": "Key removed",
    }


@app.get("/api/settings/api-key/status")
async def api_key_status(
    current_user: CurrentUser = CurrentUserDep,
):
    conn = get_db()

    try:
        cursor = conn.execute(
            """
            SELECT data
            FROM UserApiKey
            WHERE json_extract(
                data,
                '$.status'
            ) = 'active'
              AND json_extract(
                  data,
                  '$.user_id'
              ) = ?
            """,
            (current_user.id,),
        )

        row = cursor.fetchone()
    finally:
        conn.close()

    if row:
        key_data = json.loads(
            row["data"]
        )
        provider = key_data["provider"]
        model = (
            key_data.get("model")
            or load_config()[
                "default_models"
            ].get(
                provider,
                "",
            )
        )

        return {
            "active": True,
            "provider": provider,
            "model": model,
            "key_suffix": key_data.get(
                "key_suffix",
                "****",
            ),
        }

    return {
        "active": False,
        "provider": None,
        "model": None,
        "key_suffix": None,
    }


@app.get("/api/settings/providers")
async def get_providers():
    config = load_config()

    return {
        "providers": config["providers"],
        "default_models": config[
            "default_models"
        ],
    }


def get_active_llm_credentials(
    user_id: str,
):
    conn = get_db()

    try:
        cursor = conn.execute(
            """
            SELECT data
            FROM UserApiKey
            WHERE json_extract(
                data,
                '$.status'
            ) = 'active'
              AND json_extract(
                  data,
                  '$.user_id'
              ) = ?
            """,
            (user_id,),
        )

        row = cursor.fetchone()
    finally:
        conn.close()

    if not row:
        raise HTTPException(
            status_code=400,
            detail=(
                "No active API key. "
                "Add one in Settings."
            ),
        )

    key_data = json.loads(
        row["data"]
    )

    provider = key_data["provider"]
    model = key_data.get("model")

    if not model:
        model = load_config()[
            "default_models"
        ].get(provider, "")

    api_key = decrypt_api_key(
        key_data["encrypted_key"]
    )

    return (
        provider,
        api_key,
        model,
    )


def call_llm_with_retry(
    system_prompt: str = "",
    user_prompt: str = "",
    max_retries: int = 3,
    model: str | None = None,
    user_id: str | None = None,
):
    time.sleep(RATE_LIMIT_SECONDS)

    if not user_id:
        raise HTTPException(
            status_code=401,
            detail="Authentication required",
        )

    provider, api_key, active_model = (
        get_active_llm_credentials(user_id)
    )

    if model is None:
        model = active_model

    attempt = 0

    while attempt < max_retries:
        try:
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
                    "type": "json_object"
                },
            )

            return json.loads(
                response.choices[0]
                .message.content
            )

        except Exception as exc:
            error_str = str(exc)

            if (
                "401" in error_str
                or "403" in error_str
                or "invalid" in error_str.lower()
            ):
                conn = get_db()

                try:
                    conn.execute(
                        """
                        UPDATE UserApiKey
                        SET data = json_set(
                            data,
                            '$.status',
                            'expired'
                        )
                        WHERE json_extract(
                            data,
                            '$.status'
                        ) = 'active'
                          AND json_extract(
                              data,
                              '$.user_id'
                          ) = ?
                        """,
                        (user_id,),
                    )

                    conn.commit()
                finally:
                    conn.close()

                add_notification(
                    (
                        "Your API key has expired "
                        "or was rejected. Add a "
                        "new one in Settings."
                    ),
                    user_id=user_id,
                    type="error",
                )

                raise HTTPException(
                    status_code=400,
                    detail=(
                        "Your API key has expired. "
                        "Please enter a new key "
                        "in Settings."
                    ),
                ) from exc

            if (
                "429" in error_str
                or "RESOURCE_EXHAUSTED"
                in error_str
            ):
                wait_time = 30

                if "retryDelay" in error_str:
                    try:
                        wait_time = int(
                            error_str.split(
                                "retryDelay': '"
                            )[1].split("s'")[0]
                        )
                    except (
                        IndexError,
                        ValueError,
                    ):
                        pass

                attempt += 1

                if attempt >= max_retries:
                    return None

                time.sleep(wait_time)
                continue

            attempt += 1

            if attempt < max_retries:
                time.sleep(5)
                continue

            return None

    return None


async def call_llm_with_retry_async(
    system_prompt: str = "",
    user_prompt: str = "",
    max_retries: int = 3,
    model: str | None = None,
    user_id: str | None = None,
):
    await asyncio.sleep(
        RATE_LIMIT_SECONDS
    )

    if not user_id:
        raise HTTPException(
            status_code=401,
            detail="Authentication required",
        )

    provider, api_key, active_model = (
        get_active_llm_credentials(user_id)
    )

    if model is None:
        model = active_model

    attempt = 0

    while attempt < max_retries:
        try:
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
                    "type": "json_object"
                },
            )

            return json.loads(
                response.choices[0]
                .message.content
            )

        except Exception as exc:
            error_str = str(exc)

            if (
                "401" in error_str
                or "403" in error_str
                or "invalid" in error_str.lower()
            ):
                conn = get_db()

                try:
                    conn.execute(
                        """
                        UPDATE UserApiKey
                        SET data = json_set(
                            data,
                            '$.status',
                            'expired'
                        )
                        WHERE json_extract(
                            data,
                            '$.status'
                        ) = 'active'
                          AND json_extract(
                              data,
                              '$.user_id'
                          ) = ?
                        """,
                        (user_id,),
                    )

                    conn.commit()
                finally:
                    conn.close()

                return None

            if (
                "429" in error_str
                or "RESOURCE_EXHAUSTED"
                in error_str
            ):
                wait_time = 30

                if "retryDelay" in error_str:
                    try:
                        wait_time = int(
                            error_str.split(
                                "retryDelay': '"
                            )[1].split("s'")[0]
                        )
                    except (
                        IndexError,
                        ValueError,
                    ):
                        pass

                attempt += 1

                if attempt >= max_retries:
                    return None

                await asyncio.sleep(
                    wait_time
                )
                continue

            attempt += 1

            if attempt < max_retries:
                await asyncio.sleep(5)
                continue

            return None

    return None


class InvokeLLMRequest(BaseModel):
    prompt: str
    response_json_schema: dict | None = None
    file_urls: list[str] | None = None


@app.post(
    "/api/apps/local/integration-endpoints/Core/InvokeLLM"
)
async def invoke_llm(
    body: InvokeLLMRequest,
    current_user: CurrentUser = CurrentUserDep,
):
    prompt = body.prompt
    response_schema = body.response_json_schema
    file_urls = body.file_urls or []

    if not prompt:
        raise HTTPException(
            status_code=400,
            detail=(
                "Missing 'prompt' in request body."
            ),
        )

    file_text = ""

    conn = get_db()

    try:
        for file_reference_value in file_urls:
            stored_file = get_owned_file(
                conn,
                user_id=current_user.id,
                file_reference=file_reference_value,
            )

            extraction_result = (
                extract_text_from_pdf(
                    str(
                        stored_file.storage_path
                    )
                )
            )

            if extraction_result["success"]:
                file_text += (
                    "\n\n"
                    + extraction_result["text"]
                )
    finally:
        conn.close()

    schema_instruction = ""

    if response_schema:
        schema_instruction = (
            "\n\nReturn ONLY a valid JSON "
            "object matching this exact "
            "schema, no markdown or extra text:\n"
            f"{json.dumps(response_schema)}"
        )

    user_content = (
        prompt
        + schema_instruction
    )

    if file_text:
        user_content += (
            "\n\n=== ATTACHED DOCUMENT CONTENT ===\n"
            + file_text
        )

    system_prompt = (
        f"Today's date is "
        f"{date.today().strftime('%B %d, %Y')}. "
        "You are an honest, skeptical, "
        "evidence-based expert assistant. "
        "Never inflate scores. "
        "Return ONLY valid JSON."
    )

    result = await asyncio.to_thread(
        call_llm_with_retry,
        system_prompt=system_prompt,
        user_prompt=user_content,
        user_id=current_user.id,
    )

    if result:
        result["status"] = "success"

        add_notification(
            "AI analysis completed successfully.",
            user_id=current_user.id,
            type="success",
        )

        return result

    add_notification(
        (
            "AI analysis failed. "
            "Check your API key and quota."
        ),
        user_id=current_user.id,
        type="error",
    )

    raise HTTPException(
        status_code=500,
        detail=(
            "LLM call failed. "
            "Check your API key and quota."
        ),
    )


def get_job_state(
    job_id: str,
    user_id: str | None = None,
):
    conn = get_db()

    try:
        if user_id is None:
            cursor = conn.execute(
                """
                SELECT data
                FROM ScrapeJob
                WHERE id = ?
                """,
                (job_id,),
            )
        else:
            cursor = conn.execute(
                """
                SELECT data
                FROM ScrapeJob
                WHERE id = ?
                  AND json_extract(
                      data,
                      '$.user_id'
                  ) = ?
                """,
                (
                    job_id,
                    user_id,
                ),
            )

        row = cursor.fetchone()

        return (
            json.loads(row["data"])
            if row
            else None
        )
    finally:
        conn.close()


def save_job_state(
    job_id: str,
    state: dict,
):
    conn = get_db()

    try:
        conn.execute(
            """
            INSERT OR REPLACE INTO ScrapeJob
            (id, data)
            VALUES (?, ?)
            """,
            (
                job_id,
                json.dumps(state),
            ),
        )

        conn.commit()
    finally:
        conn.close()


def update_job_state(
    job_id: str,
    **updates,
):
    state = get_job_state(job_id) or {}
    state.update(updates)
    save_job_state(job_id, state)
    return state


class ScrapeJobsRequest(BaseModel):
    source_url: str
    source_name: str | None = None
    match_threshold: int = 70
    skills_weight: int = 40
    semantic_weight: int = 25
    seniority_weight: int = 15
    domain_weight: int = 20


@app.post(
    "/api/apps/local/integration-endpoints/Core/ScrapeJobs"
)
async def scrape_jobs(
    body: ScrapeJobsRequest,
    current_user: CurrentUser = CurrentUserDep,
):
    req_data = body.model_dump()
    job_id = str(uuid.uuid4())

    initial_state = {
        "id": job_id,
        "cancel": False,
        "status": "running",
        "saved": 0,
        "total": 0,
        "skipped_duplicate": 0,
        "skipped_low_score": 0,
        "created_at": date.today().isoformat(),
        "source_label": (
            req_data.get("source_name")
            or req_data.get(
                "source_url",
                "",
            )
        ),
        "stage": "Starting scan...",
        "user_id": current_user.id,
    }

    save_job_state(
        job_id,
        initial_state,
    )

    add_notification(
        (
            f"Started scanning "
            f"{initial_state['source_label']}"
        ),
        user_id=current_user.id,
        type="info",
    )

    task = asyncio.create_task(
        run_scrape(
            job_id,
            req_data,
            current_user.id,
        )
    )

    background_tasks.add(task)
    task.add_done_callback(
        background_tasks.discard
    )

    return {
        "job_id": job_id,
        "status": "started",
    }


@app.post(
    "/api/apps/local/integration-endpoints/Core/"
    "ScrapeJobs/{job_id}/stop"
)
async def stop_scrape(
    job_id: str,
    current_user: CurrentUser = CurrentUserDep,
):
    state = get_job_state(
        job_id,
        current_user.id,
    )

    if not state:
        raise HTTPException(
            status_code=404,
            detail="Job not found",
        )

    update_job_state(
        job_id,
        cancel=True,
    )

    return {
        "status": "stopping",
    }


@app.get(
    "/api/apps/local/integration-endpoints/Core/"
    "ScrapeJobs/current"
)
async def get_current_scrape(
    current_user: CurrentUser = CurrentUserDep,
):
    conn = get_db()

    try:
        cursor = conn.execute(
            """
            SELECT id, data
            FROM ScrapeJob
            WHERE json_extract(
                data,
                '$.status'
            ) = 'running'
              AND json_extract(
                  data,
                  '$.user_id'
              ) = ?
            LIMIT 1
            """,
            (current_user.id,),
        )

        row = cursor.fetchone()
    finally:
        conn.close()

    if row:
        state = json.loads(
            row["data"]
        )

        return {
            "job_id": row["id"],
            **state,
        }

    return {
        "job_id": None,
    }


@app.get(
    "/api/apps/local/integration-endpoints/Core/"
    "ScrapeJobs/{job_id}/status"
)
async def scrape_status(
    job_id: str,
    current_user: CurrentUser = CurrentUserDep,
):
    state = get_job_state(
        job_id,
        current_user.id,
    )

    if not state:
        raise HTTPException(
            status_code=404,
            detail="Job not found",
        )

    return state


def cheap_prefilter_match(
    resume_skills,
    job_title,
    job_description,
    min_overlap=1,
    min_description_chars=200,
):
    if len(
        job_description or ""
    ) < min_description_chars:
        return True

    text = (
        f"{job_title} "
        f"{job_description}"
    ).lower()

    matches = sum(
        1
        for skill in resume_skills
        if skill.lower() in text
    )

    return matches >= min_overlap


async def run_scrape(
    job_id: str,
    req_data: dict,
    user_id: str,
):
    try:
        source_url = req_data.get(
            "source_url",
            "",
        )

        source_label = (
            req_data.get("source_name")
            or source_url
        )

        match_threshold = req_data.get(
            "match_threshold",
            70,
        )

        weights = {
            "skills": req_data.get(
                "skills_weight",
                40,
            ),
            "semantic": req_data.get(
                "semantic_weight",
                25,
            ),
            "seniority": req_data.get(
                "seniority_weight",
                15,
            ),
            "domain": req_data.get(
                "domain_weight",
                20,
            ),
        }

        conn = get_db()

        try:
            cursor = conn.execute(
                """
                SELECT data
                FROM Resume
                WHERE json_extract(
                    data,
                    '$.user_id'
                ) = ?
                  AND json_extract(
                      data,
                      '$.active'
                  ) = 1
                LIMIT 1
                """,
                (user_id,),
            )

            row = cursor.fetchone()
        finally:
            conn.close()

        active_resume = (
            json.loads(row["data"])
            if row
            else None
        )

        if not active_resume:
            update_job_state(
                job_id,
                status="error",
                message=(
                    "No active resume found. "
                    "Upload a resume first."
                ),
            )
            return

        resume_skills = [
            skill.lower()
            for skill in active_resume.get(
                "skills",
                [],
            )
        ]

        update_job_state(
            job_id,
            stage="Fetching job listings...",
        )

        try:
            fetch_status, fetch_data = (
                await asyncio.wait_for(
                    asyncio.to_thread(
                        detect_and_fetch,
                        source_url,
                    ),
                    timeout=45,
                )
            )
        except asyncio.TimeoutError:
            update_job_state(
                job_id,
                status="error",
                message=(
                    "This source took too long "
                    "to respond and was skipped."
                ),
            )

            add_notification(
                (
                    f"Skipped {source_label}: "
                    "took too long to respond"
                ),
                user_id=user_id,
                type="warning",
            )

            return

        if fetch_status == "error":
            update_job_state(
                job_id,
                status="error",
                message=fetch_data,
            )

            add_notification(
                (
                    f"Failed to scan "
                    f"{source_label}: "
                    f"{fetch_data}"
                ),
                user_id=user_id,
                type="error",
            )

            return

        if fetch_status == "generic":
            update_job_state(
                job_id,
                stage=(
                    "Reading job listings with AI..."
                ),
            )

            raw_jobs = (
                await extract_jobs_via_llm_async(
                    fetch_data,
                    source_url,
                    user_id,
                )
            )

            if not raw_jobs:
                update_job_state(
                    job_id,
                    status="completed",
                    message=(
                        "No job listings found."
                    ),
                )

                add_notification(
                    (
                        f"Finished scanning "
                        f"{source_label}: "
                        "no job listings found "
                        "on the page"
                    ),
                    user_id=user_id,
                    type="info",
                )

                return
        else:
            raw_jobs = fetch_data

        conn = get_db()

        try:
            cursor = conn.execute(
                """
                SELECT data
                FROM Job
                WHERE json_extract(
                    data,
                    '$.user_id'
                ) = ?
                """,
                (user_id,),
            )

            existing_jobs = [
                json.loads(
                    row["data"]
                )
                for row in cursor.fetchall()
            ]
        finally:
            conn.close()

        existing_hashes = {
            job.get("dedup_hash")
            for job in existing_jobs
            if job.get("dedup_hash")
        }

        saved = 0
        skipped_duplicate = 0
        skipped_low_score = 0
        skipped_prefilter = 0
        total_jobs = len(raw_jobs)
        loop_start_time = time.time()

        update_job_state(
            job_id,
            total=total_jobs,
            skipped_prefilter=0,
        )

        ats_system_prompt = (
            "You are an honest, skeptical ATS "
            "matching engine. Compare the "
            "candidate profile to the job "
            "description realistically - do "
            "not inflate scores. Return ONLY "
            "valid JSON: "
            "{\"skills_score\": int (0-100), "
            "\"semantic_score\": int (0-100), "
            "\"seniority_score\": int (0-100), "
            "\"domain_score\": int (0-100), "
            "\"legitimacy_score\": int (0-100), "
            "\"match_reasons\": [string], "
            "\"skill_gaps\": [string], "
            "\"red_flags\": [string]}"
        )

        for idx, job in enumerate(
            raw_jobs,
            1,
        ):
            current_state = get_job_state(
                job_id
            )

            if (
                current_state
                and current_state.get("cancel")
            ):
                update_job_state(
                    job_id,
                    status="stopped",
                )

                add_notification(
                    (
                        f"Stopped scanning "
                        f"{source_label} "
                        f"({saved} job"
                        f"{'s' if saved != 1 else ''} "
                        "saved before stopping)"
                    ),
                    user_id=user_id,
                    type="info",
                )

                return

            jobs_processed_so_far = idx - 1
            eta_seconds = None

            if jobs_processed_so_far > 0:
                elapsed = (
                    time.time()
                    - loop_start_time
                )
                avg_per_job = (
                    elapsed
                    / jobs_processed_so_far
                )
                remaining = (
                    total_jobs
                    - jobs_processed_so_far
                )
                eta_seconds = round(
                    avg_per_job
                    * remaining
                )

            update_job_state(
                job_id,
                stage=(
                    f"Scoring job {idx} "
                    f"of {total_jobs}: "
                    f"{job.get('title', '')[:60]}"
                ),
                eta_seconds=eta_seconds,
            )

            if (
                job["dedup_hash"]
                in existing_hashes
            ):
                skipped_duplicate += 1

                update_job_state(
                    job_id,
                    skipped_duplicate=(
                        skipped_duplicate
                    ),
                )

                continue

            if (
                PREFILTER_ENABLED
                and resume_skills
                and not cheap_prefilter_match(
                    resume_skills,
                    job.get("title", ""),
                    job.get(
                        "description",
                        "",
                    ),
                )
            ):
                skipped_prefilter += 1

                update_job_state(
                    job_id,
                    skipped_prefilter=(
                        skipped_prefilter
                    ),
                )

                continue

            user_prompt = (
                f"Candidate skills: "
                f"{resume_skills}\n"
                f"Candidate seniority: "
                f"{active_resume.get('seniority')}\n"
                f"Candidate years of experience: "
                f"{active_resume.get('years_exp')}\n\n"
                f"Job Title: {job['title']}\n"
                f"Company: "
                f"{job.get('company', 'Unknown')}\n"
                f"Location: "
                f"{job.get('location', 'Not specified')}\n"
                f"Job Description: "
                f"{job['description'][:3000]}"
            )

            result = (
                await call_llm_with_retry_async(
                    system_prompt=(
                        ats_system_prompt
                    ),
                    user_prompt=user_prompt,
                    user_id=user_id,
                )
            )

            current_state = get_job_state(
                job_id
            )

            if (
                current_state
                and current_state.get("cancel")
            ):
                update_job_state(
                    job_id,
                    status="stopped",
                )

                add_notification(
                    (
                        f"Stopped scanning "
                        f"{source_label} "
                        f"({saved} job"
                        f"{'s' if saved != 1 else ''} "
                        "saved before stopping)"
                    ),
                    user_id=user_id,
                    type="info",
                )

                return

            if result is None:
                skipped_low_score += 1

                update_job_state(
                    job_id,
                    skipped_low_score=(
                        skipped_low_score
                    ),
                )

                continue

            sub_scores = {
                "skills_score": result.get(
                    "skills_score",
                    50,
                ),
                "semantic_score": result.get(
                    "semantic_score",
                    50,
                ),
                "seniority_score": result.get(
                    "seniority_score",
                    50,
                ),
                "domain_score": result.get(
                    "domain_score",
                    50,
                ),
            }

            match_score = round(
                sub_scores["skills_score"]
                * (
                    weights["skills"]
                    / 100
                )
                + sub_scores["semantic_score"]
                * (
                    weights["semantic"]
                    / 100
                )
                + sub_scores["seniority_score"]
                * (
                    weights["seniority"]
                    / 100
                )
                + sub_scores["domain_score"]
                * (
                    weights["domain"]
                    / 100
                )
            )

            if match_score < match_threshold:
                skipped_low_score += 1

                update_job_state(
                    job_id,
                    skipped_low_score=(
                        skipped_low_score
                    ),
                )

                continue

            job["match_score"] = match_score
            job["match_reasons"] = result.get(
                "match_reasons",
                [],
            )
            job["skill_gaps"] = result.get(
                "skill_gaps",
                [],
            )
            job["red_flags"] = result.get(
                "red_flags",
                [],
            )
            job["legitimacy_score"] = result.get(
                "legitimacy_score",
                100,
            )
            job["status"] = "new"
            job["dismissed"] = False

            job_row_id = str(uuid.uuid4())

            job["id"] = job_row_id
            job["created_date"] = (
                date.today().isoformat()
            )
            job["user_id"] = user_id

            conn = get_db()

            try:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO Job
                    (id, data)
                    VALUES (?, ?)
                    """,
                    (
                        job_row_id,
                        json.dumps(job),
                    ),
                )

                conn.commit()
            finally:
                conn.close()

            existing_hashes.add(
                job["dedup_hash"]
            )

            saved += 1

            update_job_state(
                job_id,
                saved=saved,
            )

        update_job_state(
            job_id,
            status="completed",
        )

        state = get_job_state(
            job_id
        )

        source_label = (
            state.get(
                "source_label",
                "a source",
            )
            if state
            else "a source"
        )

        add_notification(
            (
                f"Finished scanning "
                f"{source_label}: "
                f"{saved} new job"
                f"{'s' if saved != 1 else ''} found"
                + (
                    f" ({skipped_prefilter} "
                    "skipped instantly by "
                    "pre-filter)"
                    if skipped_prefilter
                    else ""
                )
            ),
            user_id=user_id,
            type="success",
        )

    except Exception as exc:
        update_job_state(
            job_id,
            status="error",
            message=str(exc),
        )

        add_notification(
            f"Scan failed: {exc}",
            user_id=user_id,
            type="error",
        )


async def extract_jobs_via_llm_async(
    html,
    source_url,
    user_id: str,
):
    system_prompt = (
        "You extract real job postings from "
        "raw webpage HTML. Return ONLY valid "
        "JSON: {\"jobs\": [{\"title\": string, "
        "\"company\": string, \"location\": "
        "string, \"url\": string, "
        "\"description\": string}]}. "
        "If no listings are found, return "
        "{\"jobs\": []}."
    )

    user_prompt = (
        f"Page URL: {source_url}\n\n"
        f"HTML:\n{html}"
    )

    try:
        result = (
            await call_llm_with_retry_async(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_retries=1,
                user_id=user_id,
            )
        )

        if not result:
            return []

        raw = result.get(
            "jobs",
            [],
        )

        return [
            normalize_job(job)
            for job in raw
        ]
    except Exception:
        return []


@app.post("/api/apps/local/analytics/track/batch")
async def track_analytics():
    return {
        "status": "ok",
    }


@app.get("/api/apps/local/entities/User/me")
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