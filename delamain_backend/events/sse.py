from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from starlette.requests import Request

from delamain_backend.db import Database
from delamain_backend.db.database import event_row_to_envelope
from delamain_backend.events.bus import EventBus


def format_sse(event: dict) -> str:
    data = json.dumps(event, separators=(",", ":"), sort_keys=True)
    return f"id: {event['id']}\nevent: {event['type']}\ndata: {data}\n\n"


async def stream_events(
    *,
    request: Request,
    db: Database,
    bus: EventBus,
    conversation_id: str | None = None,
    run_id: str | None = None,
    last_event_id: int | None = None,
) -> AsyncIterator[str]:
    if conversation_id is None and run_id is None:
        raise ValueError("conversation_id or run_id is required")

    if last_event_id is None:
        header = request.headers.get("last-event-id")
        if header and header.isdigit():
            last_event_id = int(header)
    last_event_id = last_event_id or 0

    if conversation_id is not None:
        queue = await bus.subscribe(conversation_id=conversation_id)
        rows = await db.fetchall(
            "SELECT * FROM events WHERE conversation_id = ? AND id > ? ORDER BY id ASC",
            (conversation_id, last_event_id),
        )
    else:
        queue = await bus.subscribe(run_id=run_id)
        rows = await db.fetchall(
            "SELECT * FROM events WHERE run_id = ? AND id > ? ORDER BY id ASC",
            (run_id, last_event_id),
        )

    try:
        max_sent_id = last_event_id
        for row in rows:
            event = event_row_to_envelope(row)
            max_sent_id = max(max_sent_id, event["id"])
            yield format_sse(event)

        while not await request.is_disconnected():
            try:
                event = await asyncio.wait_for(queue.get(), timeout=15)
                if event["id"] <= max_sent_id:
                    continue
                max_sent_id = event["id"]
                yield format_sse(event)
            except asyncio.TimeoutError:
                yield ": keep-alive\n\n"
    finally:
        await bus.unsubscribe(queue, conversation_id=conversation_id, run_id=run_id)
