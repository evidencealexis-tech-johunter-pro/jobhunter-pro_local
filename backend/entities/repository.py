from __future__ import annotations

import json

from core import database


def fetch_rows(
    entity_name: str,
    user_id: str,
    user_scoped: bool,
):
    conn = database.get_db()
    try:
        if user_scoped:
            cursor = conn.execute(
                f"""
                SELECT data
                FROM {entity_name}
                WHERE json_extract(data, '$.user_id') = ?
                """,
                (user_id,),
            )
        else:
            cursor = conn.execute(
                f"SELECT data FROM {entity_name}"
            )
        return cursor.fetchall()
    finally:
        conn.close()


def create_entity(
    entity_name: str,
    item_id: str,
    data: dict,
):
    conn = database.get_db()
    try:
        conn.execute(
            f"""
            INSERT OR REPLACE INTO {entity_name}
            (id, data)
            VALUES (?, ?)
            """,
            (item_id, json.dumps(data)),
        )
        conn.commit()
    finally:
        conn.close()


def deactivate_other_resumes(
    user_id: str,
):
    conn = database.get_db()
    try:
        conn.execute(
            """
            UPDATE Resume
            SET data = json_set(
                data,
                '$.active',
                json('false')
            )
            WHERE json_extract(data, '$.user_id') = ?
            """,
            (user_id,),
        )
        conn.commit()
    finally:
        conn.close()


def get_entity(
    entity_name: str,
    item_id: str,
    user_id: str,
    user_scoped: bool,
):
    conn = database.get_db()
    try:
        if user_scoped:
            cursor = conn.execute(
                f"""
                SELECT data
                FROM {entity_name}
                WHERE id = ?
                  AND json_extract(data, '$.user_id') = ?
                """,
                (item_id, user_id),
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
        return json.loads(row["data"]) if row else None
    finally:
        conn.close()


def update_entity(
    entity_name: str,
    item_id: str,
    data: dict,
):
    conn = database.get_db()
    try:
        conn.execute(
            f"""
            UPDATE {entity_name}
            SET data = ?
            WHERE id = ?
            """,
            (json.dumps(data), item_id),
        )
        conn.commit()
    finally:
        conn.close()


def delete_entity(
    entity_name: str,
    item_id: str,
    user_id: str,
    user_scoped: bool,
) -> int:
    conn = database.get_db()
    try:
        if user_scoped:
            cursor = conn.execute(
                f"""
                DELETE FROM {entity_name}
                WHERE id = ?
                  AND json_extract(data, '$.user_id') = ?
                """,
                (item_id, user_id),
            )
        else:
            cursor = conn.execute(
                f"""
                DELETE FROM {entity_name}
                WHERE id = ?
                """,
                (item_id,),
            )
        conn.commit()
        return cursor.rowcount
    finally:
        conn.close()