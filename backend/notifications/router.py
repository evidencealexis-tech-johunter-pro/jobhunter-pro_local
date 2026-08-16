from __future__ import annotations

from fastapi import APIRouter

from auth import CurrentUser, CurrentUserDep

from .service import (
    clear_user_notifications,
    get_user_notifications,
    mark_all_user_notifications_read,
)


router = APIRouter()


@router.get("/api/notifications")
async def get_notifications(
    limit: int = 50,
    current_user: CurrentUser = CurrentUserDep,
):
    return get_user_notifications(
        user_id=current_user.id,
        limit=limit,
    )


@router.post("/api/notifications/mark-all-read")
async def mark_all_notifications_read(
    current_user: CurrentUser = CurrentUserDep,
):
    mark_all_user_notifications_read(
        user_id=current_user.id,
    )
    return {"status": "success"}


@router.delete("/api/notifications")
async def clear_notifications(
    current_user: CurrentUser = CurrentUserDep,
):
    clear_user_notifications(
        user_id=current_user.id,
    )
    return {"status": "success"}
