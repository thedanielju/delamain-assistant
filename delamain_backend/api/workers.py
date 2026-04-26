from __future__ import annotations

import asyncio
import json
from contextlib import suppress

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket
from pydantic import BaseModel
from starlette.websockets import WebSocketDisconnect

from delamain_backend.api.deps import get_worker_manager, get_worker_registry
from delamain_backend.workers import WorkerManager
from delamain_backend.workers.registry import WorkerTypeRegistry

router = APIRouter(tags=["workers"])
PTY_INITIAL_LINES = 200
PTY_STREAM_LINES = 2000


class WorkerStartRequest(BaseModel):
    worker_type: str
    name: str | None = None
    conversation_id: str | None = None


class WorkerRenameRequest(BaseModel):
    name: str


@router.get("/workers/types")
async def list_worker_types(
    include_readiness: bool = Query(False),
    refresh_readiness: bool = Query(False),
    registry: WorkerTypeRegistry = Depends(get_worker_registry),
):
    return {
        "types": await registry.list_public(
            include_readiness=include_readiness,
            refresh_readiness=refresh_readiness,
        )
    }


@router.get("/workers")
async def list_workers(
    status: str | None = Query(None),
    conversation_id: str | None = Query(None),
    include_readiness: bool = Query(False),
    refresh_readiness: bool = Query(False),
    mgr: WorkerManager = Depends(get_worker_manager),
):
    workers = await mgr.list_workers(
        status_filter=status,
        conversation_id=conversation_id,
        include_readiness=include_readiness,
        refresh_readiness=refresh_readiness,
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
    include_readiness: bool = Query(False),
    refresh_readiness: bool = Query(False),
    mgr: WorkerManager = Depends(get_worker_manager),
):
    try:
        if refresh:
            return await mgr.refresh_status(
                worker_id,
                include_readiness=include_readiness,
                refresh_readiness=refresh_readiness,
            )
        return await mgr.get_worker(
            worker_id,
            include_readiness=include_readiness,
            refresh_readiness=refresh_readiness,
        )
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


@router.websocket("/workers/{worker_id}/pty")
async def worker_pty(
    websocket: WebSocket,
    worker_id: str,
    snapshot: bool = Query(True),
    lines: int = Query(PTY_INITIAL_LINES, ge=1, le=2000),
):
    mgr: WorkerManager = websocket.app.state.worker_manager
    await websocket.accept()

    try:
        await mgr.prepare_pty(worker_id)
    except ValueError as exc:
        await _send_pty_error_and_close(websocket, str(exc), code=1008)
        return

    input_task = asyncio.create_task(_worker_pty_input_loop(websocket, mgr, worker_id))
    output_task = asyncio.create_task(
        _worker_pty_output_loop(
            websocket,
            mgr,
            worker_id,
            snapshot=snapshot,
            initial_lines=lines,
        )
    )
    done, pending = await asyncio.wait(
        {input_task, output_task},
        return_when=asyncio.FIRST_COMPLETED,
    )
    for task in pending:
        task.cancel()
    for task in pending:
        with suppress(asyncio.CancelledError):
            await task
    for task in done:
        with suppress(WebSocketDisconnect, RuntimeError):
            task.result()


async def _worker_pty_input_loop(
    websocket: WebSocket,
    mgr: WorkerManager,
    worker_id: str,
) -> None:
    while True:
        try:
            message = await websocket.receive()
        except (WebSocketDisconnect, RuntimeError):
            return
        if message.get("type") == "websocket.disconnect":
            return

        data = _pty_input_data(message)
        if data is None:
            continue
        try:
            await mgr.send_terminal_input(worker_id, data)
        except ValueError as exc:
            await _send_pty_error_and_close(websocket, str(exc), code=1011)
            return


async def _worker_pty_output_loop(
    websocket: WebSocket,
    mgr: WorkerManager,
    worker_id: str,
    *,
    snapshot: bool,
    initial_lines: int,
) -> None:
    subscription = None
    try:
        subscription = await mgr.subscribe_pty_output(worker_id)
        if snapshot:
            output = await mgr.capture_pty_output(worker_id, lines=PTY_STREAM_LINES)
            await websocket.send_json(
                {"type": "snapshot", "data": _tail_lines(_trim_trailing_blank_lines(output), initial_lines)}
            )

        while True:
            event = await subscription.receive()
            if isinstance(event, str):
                await websocket.send_json({"type": "data", "data": event})
                continue
            if event is None:
                return
            if event.kind == "closed":
                if event.data:
                    frame = {"type": "data", "data": event.data}
                    if event.dropped_chunks:
                        frame["dropped_chunks"] = event.dropped_chunks
                        frame["dropped_bytes"] = event.dropped_bytes
                    await websocket.send_json(frame)
                if event.message:
                    await _send_pty_error_and_close(websocket, event.message, code=1011)
                return
            frame = {"type": "data", "data": event.data}
            if event.dropped_chunks:
                frame["dropped_chunks"] = event.dropped_chunks
                frame["dropped_bytes"] = event.dropped_bytes
            await websocket.send_json(frame)
    except WebSocketDisconnect:
        return
    except ValueError as exc:
        await _send_pty_error_and_close(websocket, str(exc), code=1011)
    except RuntimeError:
        return
    finally:
        if subscription is not None:
            await subscription.close()


def _pty_input_data(message: dict) -> str | None:
    text = message.get("text")
    if isinstance(text, str):
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return text
        if not isinstance(payload, dict):
            return None
        if payload.get("type") != "input":
            return None
        data = payload.get("data")
        return data if isinstance(data, str) else None

    data = message.get("bytes")
    if isinstance(data, bytes):
        return data.decode("utf-8", errors="replace")
    return None


def _tail_lines(text: str, lines: int) -> str:
    if lines <= 0:
        return ""
    parts = text.splitlines(keepends=True)
    if lines >= len(parts):
        return text
    return "".join(parts[-lines:])


def _trim_trailing_blank_lines(text: str) -> str:
    parts = text.splitlines(keepends=True)
    while parts and not parts[-1].strip():
        parts.pop()
    return "".join(parts)


async def _send_pty_error_and_close(websocket: WebSocket, message: str, *, code: int) -> None:
    with suppress(Exception):
        await websocket.send_json({"type": "error", "message": message})
    with suppress(Exception):
        await websocket.close(code=code, reason=message[:120])
