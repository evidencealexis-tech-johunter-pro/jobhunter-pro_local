from __future__ import annotations

import json
from datetime import date
from typing import Any
import uuid

from core import database


def find_active_key(user_id: str) -> Any | None:
    conn = database.get_db()
    try:
        return conn.execute(
            """
            SELECT data
            FROM UserApiKey
            WHERE json_extract(data, '$.status') = 'active'
              AND json_extract(data, '$.user_id') = ?
            LIMIT 1
            """,
            (user_id,),
        ).fetchone()
    finally:
        conn.close()


def create_active_key(
    *,
    user_id: str,
    provider: str,
    encrypted_key: str,
    key_suffix: str,
    model: str | None,
    label: str,
    base_url: str | None = None,
) -> None:
    conn = database.get_db()
    try:
        rows = conn.execute(
            """
            SELECT data
            FROM UserApiKey
            WHERE json_extract(data, '$.status') = 'active'
              AND json_extract(data, '$.user_id') = ?
            """,
            (user_id,),
        ).fetchall()

        for row in rows:
            existing = json.loads(row["data"])
            existing["status"] = "revoked"
            conn.execute(
                "UPDATE UserApiKey SET data = ? WHERE id = ?",
                (json.dumps(existing), existing["id"]),
            )

        new_id = str(uuid.uuid4())
        key_data: dict[str, Any] = {
            "id": new_id,
            "user_id": user_id,
            "provider": provider,
            "encrypted_key": encrypted_key,
            "key_suffix": key_suffix,
            "status": "active",
            "created_at": date.today().isoformat(),
            "label": label,
            "model": model,
        }
        if base_url:
            key_data["base_url"] = base_url

        conn.execute(
            "INSERT INTO UserApiKey (id, data) VALUES (?, ?)",
            (new_id, json.dumps(key_data)),
        )
        conn.commit()
    finally:
        conn.close()


def revoke_active_key(user_id: str) -> bool:
    conn = database.get_db()
    try:
        row = conn.execute(
            """
            SELECT data
            FROM UserApiKey
            WHERE json_extract(data, '$.status') = 'active'
              AND json_extract(data, '$.user_id') = ?
            LIMIT 1
            """,
            (user_id,),
        ).fetchone()
        if not row:
            return False

        data = json.loads(row["data"])
        data["status"] = "revoked"
        conn.execute(
            "UPDATE UserApiKey SET data = ? WHERE id = ?",
            (json.dumps(data), data["id"]),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def expire_active_keys(user_id: str) -> None:
    conn = database.get_db()
    try:
        rows = conn.execute(
            """
            SELECT data
            FROM UserApiKey
            WHERE json_extract(data, '$.status') = 'active'
              AND json_extract(data, '$.user_id') = ?
            """,
            (user_id,),
        ).fetchall()
        for row in rows:
            data = json.loads(row["data"])
            data["status"] = "expired"
            conn.execute(
                "UPDATE UserApiKey SET data = ? WHERE id = ?",
                (json.dumps(data), data["id"]),
            )
        conn.commit()
    finally:
        conn.close()