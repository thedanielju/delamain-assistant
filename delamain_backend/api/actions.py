from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from delamain_backend.actions import ActionRunner, default_action_registry
from delamain_backend.api.deps import get_bus, get_config, get_db
from delamain_backend.config import AppConfig
from delamain_backend.db import Database
from delamain_backend.errors import ToolPolicyDenied
from delamain_backend.events import EventBus
from delamain_backend.schemas import ActionExecuteRequest

router = APIRouter(tags=["actions"])


@router.get("/actions")
async def list_actions(config: AppConfig = Depends(get_config)):
    return {"actions": default_action_registry(config).list()}


@router.post("/actions/{action_id}", status_code=status.HTTP_202_ACCEPTED)
async def execute_action(
    action_id: str,
    payload: ActionExecuteRequest | None = None,
    config: AppConfig = Depends(get_config),
    db: Database = Depends(get_db),
    bus: EventBus = Depends(get_bus),
):
    runner = ActionRunner(
        config=config,
        db=db,
        bus=bus,
        registry=default_action_registry(config),
    )
    try:
        return await runner.execute(
            action_id,
            conversation_id=payload.conversation_id if payload else None,
        )
    except ToolPolicyDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
