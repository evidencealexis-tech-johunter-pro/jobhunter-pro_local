from __future__ import annotations

import json
from typing import Any

from core import database


def get_job_state(
    job_id: str,
    user_id: str | None = None,
) -> dict[str, Any] | None:
    conn = database.get_db()

    try:
        if user_id is None:
            row = conn.execute(
                """
                SELECT data
                FROM ScrapeJob
                WHERE id = ?
                """,
                (job_id,),
            ).fetchone()
        else:
            row = conn.execute(
                """
                SELECT data
                FROM ScrapeJob
                WHERE id = ?
                  AND json_extract(data, '$.user_id') = ?
                """,
                (
                    job_id,
                    user_id,
                ),
            ).fetchone()

        if not row:
            return None

        return json.loads(row["data"])
    finally:
        conn.close()


def save_job_state(
    job_id: str,
    state: dict[str, Any],
) -> None:
    conn = database.get_db()

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


def get_running_job_for_user(
    user_id: str,
) -> dict[str, Any] | None:
    conn = database.get_db()

    try:
        row = conn.execute(
            """
            SELECT id, data
            FROM ScrapeJob
            WHERE json_extract(data, '$.status') = 'running'
              AND json_extract(data, '$.user_id') = ?
            LIMIT 1
            """,
            (user_id,),
        ).fetchone()

        if not row:
            return None

        return {
            "job_id": row["id"],
            **json.loads(row["data"]),
        }
    finally:
        conn.close()


def clear_jobs_for_user(
    user_id: str,
) -> None:
    conn = database.get_db()

    try:
        conn.execute(
            """
            DELETE FROM Job
            WHERE json_extract(data, '$.user_id') = ?
            """,
            (user_id,),
        )
        conn.commit()
    finally:
        conn.close()