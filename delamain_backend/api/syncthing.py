from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from delamain_backend.api.audit import audit_event
from delamain_backend.api.deps import get_bus, get_config, get_db
from delamain_backend.config import AppConfig
from delamain_backend.db import Database
from delamain_backend.errors import ToolPolicyDenied
from delamain_backend.events import EventBus
from delamain_backend.schemas import SyncthingConflictResolveRequest
from delamain_backend.syncthing_status import (
    resolve_syncthing_conflict,
    syncthing_conflicts,
    syncthing_summary,
)

router = APIRouter(tags=["syncthing"])


@router.get("/syncthing/summary")
async def get_syncthing_summary(config: AppConfig = Depends(get_config)):
    return syncthing_summary(config)


@router.get("/syncthing/conflicts")
async def get_syncthing_conflicts(config: AppConfig = Depends(get_config)):
    return syncthing_conflicts(config)


@router.post("/syncthing/conflicts/resolve")
async def resolve_conflict(
    payload: SyncthingConflictResolveRequest,
    config: AppConfig = Depends(get_config),
    db: Database = Depends(get_db),
    bus: EventBus = Depends(get_bus),
):
    try:
        result = resolve_syncthing_conflict(
            config,
            path=payload.path,
            action=payload.action,
            note=payload.note,
        )
    except ToolPolicyDenied as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await audit_event(
        db=db,
        bus=bus,
        conversation_id=None,
        action="syncthing.conflict_resolved",
        summary=f"Syncthing conflict {payload.action}: {payload.path}",
        payload=result,
    )
    return result
