from __future__ import annotations

import uuid
from datetime import datetime, timezone

from .repository import (
    create_notification,
    delete_all,
    list_notifications,
    mark_all_read,
)


def add_notification(
    message: str,
    user_id: str,
    type: str = "info",
    context: str | None = None,
) -> None:
    if not user_id:
        raise ValueError("Notification owner is required")

    notification_id = str(uuid.uuid4())
    data = {
        "id": notification_id,
        "user_id": user_id,
        "message": message,
        "type": type,
        "context": context,
        "read": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    create_notification(
        notification_id=notification_id,
        data=data,
    )


def get_user_notifications(
    *,
    user_id: str,
    limit: int,
) -> dict:
    limit = max(1, min(limit, 100))

    items = list_notifications(user_id=user_id)
    items.sort(
        key=lambda notification: notification.get("created_at", ""),
        reverse=True,
    )

    unread_count = sum(
        1
        for notification in items
        if not notification.get("read")
    )

    return {
        "notifications": items[:limit],
        "unread_count": unread_count,
    }


def mark_all_user_notifications_read(
    *,
    user_id: str,
) -> None:
    mark_all_read(user_id=user_id)


def clear_user_notifications(
    *,
    user_id: str,
) -> None:
    delete_all(user_id=user_id)