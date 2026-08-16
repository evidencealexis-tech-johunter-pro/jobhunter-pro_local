from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone

from core.database import get_db


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def add_notification(
    message: str,
    user_id: str,
    type: str = "info",
    context: str | None = None,
) -> None:
    if not user_id:
        raise ValueError("Notification owner is required")

    notification_id = str(uuid.uuid4())
    notification = {
        "id": notification_id,
        "user_id": user_id,
        "message": message,
        "type": type,
        "context": context,
        "read": False,
        "created_at": _utc_now_iso(),
    }

    conn = get_db()
    try:
        conn.execute(
            """
            INSERT INTO Notification (id, data)
            VALUES (?, ?)
            """,
            (notification_id, json.dumps(notification)),
        )
        conn.commit()
    finally:
        conn.close()


def list_notifications_for_user(
    user_id: str,
    limit: int = 50,
) -> tuple[list[dict], int]:
    limit = max(1, min(limit, 100))

    conn = get_db()
    try:
        rows = conn.execute(
            """
            SELECT data
            FROM Notification
            WHERE json_extract(data, '$.user_id') = ?
            """,
            (user_id,),
        ).fetchall()
    finally:
        conn.close()

    items = [json.loads(row["data"]) for row in rows]
    items.sort(
        key=lambda item: item.get("created_at", ""),
        reverse=True,
    )

    unread_count = sum(1 for item in items if not item.get("read"))
    return items[:limit], unread_count


def mark_all_notifications_read(user_id: str) -> None:
    conn = get_db()
    try:
        rows = conn.execute(
            """
            SELECT data
            FROM Notification
            WHERE json_extract(data, '$.user_id') = ?
            """,
            (user_id,),
        ).fetchall()

        for row in rows:
            notification = json.loads(row["data"])
            notification["read"] = True
            conn.execute(
                """
                UPDATE Notification
                SET data = ?
                WHERE id = ?
                """,
                (json.dumps(notification), notification["id"]),
            )

        conn.commit()
    finally:
        conn.close()


def clear_notifications_for_user(user_id: str) -> None:
    conn = get_db()
    try:
        conn.execute(
            """
            DELETE FROM Notification
            WHERE json_extract(data, '$.user_id') = ?
            """,
            (user_id,),
        )
        conn.commit()
    finally:
        conn.close()
