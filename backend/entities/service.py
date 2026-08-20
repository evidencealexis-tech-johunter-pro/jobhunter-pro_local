from __future__ import annotations

import json
import uuid
from datetime import date

from fastapi import HTTPException

from entities import repository

VALID_ENTITIES = {
    "Resume",
    "Job",
    "Notification",
    "ScrapeSource",
    "ContextDocument",
    "AppSettings",
    "ScrapeJob",
    "UserApiKey",
}

USER_SCOPED_ENTITIES = {"Resume", "Job"}
MANAGED_ENTITIES = {"UserApiKey", "Notification"}


def validate_entity(entity_name: str) -> str:
    if entity_name not in VALID_ENTITIES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid entity: {entity_name}",
        )

    if entity_name in MANAGED_ENTITIES:
        raise HTTPException(
            status_code=403,
            detail=(
                "This entity is managed through "
                "authenticated endpoints"
            ),
        )

    return entity_name


def is_user_scoped(entity_name: str) -> bool:
    return entity_name in USER_SCOPED_ENTITIES


def list_entities(
    entity_name: str,
    user_id: str,
    query: str | None = None,
    sort: str | None = None,
    limit: int | None = None,
):
    validate_entity(entity_name)

    rows = repository.fetch_rows(
        entity_name,
        user_id,
        is_user_scoped(entity_name),
    )

    items = [json.loads(row["data"]) for row in rows]

    if query:
        try:
            filters = json.loads(query)
        except json.JSONDecodeError as exc:
            raise HTTPException(
                status_code=400,
                detail="Invalid JSON in filter",
            ) from exc

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

    if sort:
        descending = sort.startswith("-")
        field = sort[1:] if descending else sort
        items.sort(
            key=lambda item: str(item.get(field) or ""),
            reverse=descending,
        )

    if limit is not None:
        items = items[:limit]

    return items


def create_entity_record(
    entity_name: str,
    data: dict,
    user_id: str,
):
    validate_entity(entity_name)

    item_id = data.get("id") or str(uuid.uuid4())
    data["id"] = item_id

    if "created_date" not in data:
        data["created_date"] = date.today().isoformat()

    if is_user_scoped(entity_name):
        data["user_id"] = user_id

    if entity_name == "Resume" and data.get("active") is True:
        repository.deactivate_other_resumes(user_id)

    repository.create_entity(
        entity_name,
        item_id,
        data,
    )

    return data


def update_entity_record(
    entity_name: str,
    item_id: str,
    updates: dict,
    user_id: str,
):
    validate_entity(entity_name)

    existing = repository.get_entity(
        entity_name,
        item_id,
        user_id,
        is_user_scoped(entity_name),
    )

    if existing is None:
        raise HTTPException(
            status_code=404,
            detail="Item not found",
        )

    if is_user_scoped(entity_name):
        updates.pop("user_id", None)
        existing["user_id"] = user_id

    existing.update(updates)
    existing["id"] = item_id

    if entity_name == "Resume" and existing.get("active") is True:
        repository.deactivate_other_resumes(user_id)

    repository.update_entity(
        entity_name,
        item_id,
        existing,
    )

    return existing


def delete_entity_record(
    entity_name: str,
    item_id: str,
    user_id: str,
):
    validate_entity(entity_name)

    if item_id == "undefined":
        return {"status": "ignored"}

    deleted = repository.delete_entity(
        entity_name,
        item_id,
        user_id,
        is_user_scoped(entity_name),
    )

    if is_user_scoped(entity_name) and deleted == 0:
        raise HTTPException(
            status_code=404,
            detail="Item not found",
        )

    return {"status": "deleted"}