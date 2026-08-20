from __future__ import annotations

from fastapi import APIRouter

from auth import CurrentUser, CurrentUserDep

from .service import (
    SaveApiKeyRequest,
    api_key_status,
    get_providers,
    remove_api_key,
    save_api_key,
)


router = APIRouter()


@router.post("/api/settings/api-key")
async def save_api_key_route(
    body: SaveApiKeyRequest,
    current_user: CurrentUser = CurrentUserDep,
):
    return save_api_key(body, current_user.id)


@router.delete("/api/settings/api-key")
async def remove_api_key_route(
    current_user: CurrentUser = CurrentUserDep,
):
    return remove_api_key(current_user.id)


@router.get("/api/settings/api-key/status")
async def api_key_status_route(
    current_user: CurrentUser = CurrentUserDep,
):
    return api_key_status(current_user.id)


@router.get("/api/settings/providers")
async def get_providers_route():
    return get_providers()