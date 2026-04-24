from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from delamain_backend.api.deps import get_worker_manager, get_worker_registry
from delamain_backend.workers import WorkerManager
from delamain_backend.workers.registry import WorkerTypeRegistry

router = APIRouter(tags=["workers"])


class WorkerStartRequest(BaseModel):
    worker_type: str
    name: str | None = None
    conversation_id: str | None = None


class WorkerRenameRequest(BaseModel):
    name: str


@router.get("/workers/types")
async def list_worker_types(registry: WorkerTypeRegistry = Depends(get_worker_registry)):
    return {"types": registry.list()}


@router.get("/workers")
async def list_workers(
    status: str | None = Query(None),
    conversation_id: str | None = Query(None),
    mgr: WorkerManager = Depends(get_worker_manager),
):
    workers = await mgr.list_workers(
        status_filter=status,
        conversation_id=conversation_id,
    )
    return {"workers": workers}


@router.post("/workers", status_code=202)
async def start_worker(
    payload: WorkerStartRequest,
    mgr: WorkerManager = Depends(get_worker_manager),
):
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
    mgr: WorkerManager = Depends(get_worker_manager),
):
    try:
        if refresh:
            return await mgr.refresh_status(worker_id)
        return await mgr.get_worker(worker_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/workers/{worker_id}")
async def rename_worker(
    worker_id: str,
    payload: WorkerRenameRequest,
    mgr: WorkerManager = Depends(get_worker_manager),
):
    try:
        return await mgr.rename(worker_id, payload.name)
    except ValueError as exc:
        detail = str(exc)
        status_code = 404 if "not found" in detail.lower() else 400
        raise HTTPException(status_code=status_code, detail=detail) from exc


@router.post("/workers/{worker_id}/stop")
async def stop_worker(
    worker_id: str,
    mgr: WorkerManager = Depends(get_worker_manager),
):
    try:
        return await mgr.stop(worker_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/workers/{worker_id}")
async def kill_worker(
    worker_id: str,
    mgr: WorkerManager = Depends(get_worker_manager),
):
    try:
        return await mgr.kill(worker_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/workers/{worker_id}/output")
async def get_worker_output(
    worker_id: str,
    lines: int = Query(200, ge=1, le=2000),
    mgr: WorkerManager = Depends(get_worker_manager),
):
    try:
        return await mgr.capture_output(worker_id, lines=lines)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
