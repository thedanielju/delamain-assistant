from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from delamain_backend.api.deps import get_bus, get_config, get_db
from delamain_backend.config import AppConfig
from delamain_backend.db import Database
from delamain_backend.events import EventBus
from delamain_backend.workers import WorkerManager, default_worker_registry

router = APIRouter(tags=["workers"])


class WorkerStartRequest(BaseModel):
    worker_type: str
    name: str | None = None
    conversation_id: str | None = None


def _manager(config: AppConfig, db: Database, bus: EventBus) -> WorkerManager:
    return WorkerManager(
        config=config,
        db=db,
        bus=bus,
        registry=default_worker_registry(config),
    )


@router.get("/workers/types")
async def list_worker_types(config: AppConfig = Depends(get_config)):
    return {"types": default_worker_registry(config).list()}


@router.get("/workers")
async def list_workers(
    status: str | None = Query(None),
    conversation_id: str | None = Query(None),
    config: AppConfig = Depends(get_config),
    db: Database = Depends(get_db),
    bus: EventBus = Depends(get_bus),
):
    mgr = _manager(config, db, bus)
    workers = await mgr.list_workers(
        status_filter=status,
        conversation_id=conversation_id,
    )
    return {"workers": workers}


@router.post("/workers", status_code=202)
async def start_worker(
    payload: WorkerStartRequest,
    config: AppConfig = Depends(get_config),
    db: Database = Depends(get_db),
    bus: EventBus = Depends(get_bus),
):
    mgr = _manager(config, db, bus)
    try:
        return await mgr.start(
            payload.worker_type,
            name=payload.name,
            conversation_id=payload.conversation_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/workers/{worker_id}")
async def get_worker(
    worker_id: str,
    refresh: bool = Query(False),
    config: AppConfig = Depends(get_config),
    db: Database = Depends(get_db),
    bus: EventBus = Depends(get_bus),
):
    mgr = _manager(config, db, bus)
    try:
        if refresh:
            return await mgr.refresh_status(worker_id)
        return await mgr.get_worker(worker_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/workers/{worker_id}/stop")
async def stop_worker(
    worker_id: str,
    config: AppConfig = Depends(get_config),
    db: Database = Depends(get_db),
    bus: EventBus = Depends(get_bus),
):
    mgr = _manager(config, db, bus)
    try:
        return await mgr.stop(worker_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/workers/{worker_id}")
async def kill_worker(
    worker_id: str,
    config: AppConfig = Depends(get_config),
    db: Database = Depends(get_db),
    bus: EventBus = Depends(get_bus),
):
    mgr = _manager(config, db, bus)
    try:
        return await mgr.kill(worker_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/workers/{worker_id}/output")
async def get_worker_output(
    worker_id: str,
    lines: int = Query(200, ge=1, le=2000),
    config: AppConfig = Depends(get_config),
    db: Database = Depends(get_db),
    bus: EventBus = Depends(get_bus),
):
    mgr = _manager(config, db, bus)
    try:
        return await mgr.capture_output(worker_id, lines=lines)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
