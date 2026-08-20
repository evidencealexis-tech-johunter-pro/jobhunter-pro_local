from __future__ import annotations

import json
import sys

from core.database import get_db as core_get_db


def _get_db():
    main_module = sys.modules.get("main")
    getter = getattr(main_module, "get_db", None) if main_module else None
    return getter() if getter else core_get_db()


def create_notification(
    *,
    notification_id: str,
    data: dict,
) -> None:
    conn = _get_db()
    try:
        conn.execute(
            "INSERT INTO Notification (id, data) VALUES (?, ?)",
            (notification_id, json.dumps(data)),
        )
        conn.commit()
    finally:
        conn.close()


def list_notifications(
    *,
    user_id: str,
) -> list[dict]:
    conn = _get_db()
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

    return [json.loads(row["data"]) for row in rows]


def mark_all_read(
    *,
    user_id: str,
) -> None:
    conn = _get_db()
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
            data = json.loads(row["data"])
            data["read"] = True

            conn.execute(
                "UPDATE Notification SET data = ? WHERE id = ?",
                (json.dumps(data), data["id"]),
            )

        conn.commit()
    finally:
        conn.close()


def delete_all(
    *,
    user_id: str,
) -> None:
    conn = _get_db()
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