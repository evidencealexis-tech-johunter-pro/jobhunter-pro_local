from __future__ import annotations

from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

from authentication import CurrentUser, CurrentUserDep
from entities.service import (
    create_entity_record,
    delete_entity_record,
    list_entities,
    update_entity_record,
)

router = APIRouter()


class EntityPayload(BaseModel):
    model_config = {
        "extra": "allow",
    }


@router.get(
    "/api/apps/local/entities/{entity_name}"
)
async def get_entities(
    entity_name: str,
    q: Optional[str] = None,
    sort: Optional[str] = None,
    limit: Optional[int] = None,
    current_user: CurrentUser = CurrentUserDep,
):
    return list_entities(
        entity_name=entity_name,
        user_id=current_user.id,
        query=q,
        sort=sort,
        limit=limit,
    )


@router.post(
    "/api/apps/local/entities/{entity_name}"
)
async def post_entities(
    entity_name: str,
    body: EntityPayload,
    current_user: CurrentUser = CurrentUserDep,
):
    return create_entity_record(
        entity_name=entity_name,
        data=body.model_dump(),
        user_id=current_user.id,
    )


@router.put(
    "/api/apps/local/entities/{entity_name}/{item_id}"
)
@router.patch(
    "/api/apps/local/entities/{entity_name}/{item_id}"
)
async def update_entity(
    entity_name: str,
    item_id: str,
    body: EntityPayload,
    current_user: CurrentUser = CurrentUserDep,
):
    return update_entity_record(
        entity_name=entity_name,
        item_id=item_id,
        updates=body.model_dump(),
        user_id=current_user.id,
    )


@router.delete(
    "/api/apps/local/entities/{entity_name}/{item_id}"
)
async def delete_entity(
    entity_name: str,
    item_id: str,
    current_user: CurrentUser = CurrentUserDep,
):
    return delete_entity_record(
        entity_name=entity_name,
        item_id=item_id,
        user_id=current_user.id,
    )


@router.delete(
    "/api/apps/local/entities/{entity_name}"
)
async def delete_entity_by_query(
    entity_name: str,
    id: str,
    current_user: CurrentUser = CurrentUserDep,
):
    return delete_entity_record(
        entity_name=entity_name,
        item_id=id,
        user_id=current_user.id,
    )