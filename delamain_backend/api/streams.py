from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from delamain_backend.api.deps import get_bus, get_db
from delamain_backend.db import Database
from delamain_backend.events import EventBus, stream_events

router = APIRouter(tags=["streams"])


@router.get("/conversations/{conversation_id}/stream")
async def conversation_stream(
    conversation_id: str,
    request: Request,
    db: Database = Depends(get_db),
    bus: EventBus = Depends(get_bus),
):
    return StreamingResponse(
        stream_events(
            request=request,
            db=db,
            bus=bus,
            conversation_id=conversation_id,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/runs/{run_id}/stream")
async def run_stream(
    run_id: str,
    request: Request,
    db: Database = Depends(get_db),
    bus: EventBus = Depends(get_bus),
):
    return StreamingResponse(
        stream_events(request=request, db=db, bus=bus, run_id=run_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
