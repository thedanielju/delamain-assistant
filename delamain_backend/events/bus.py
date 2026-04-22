from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any

from delamain_backend.db import Database


class EventBus:
    def __init__(self, db: Database):
        self.db = db
        self._conversation_subscribers: dict[str, set[asyncio.Queue[dict[str, Any]]]] = (
            defaultdict(set)
        )
        self._run_subscribers: dict[str, set[asyncio.Queue[dict[str, Any]]]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def emit(
        self,
        *,
        conversation_id: str,
        run_id: str | None,
        event_type: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        envelope = await self.db.insert_event(
            conversation_id=conversation_id,
            run_id=run_id,
            event_type=event_type,
            payload=payload,
        )
        async with self._lock:
            subscribers = list(self._conversation_subscribers.get(conversation_id, set()))
            if run_id is not None:
                subscribers.extend(self._run_subscribers.get(run_id, set()))
        for queue in subscribers:
            try:
                queue.put_nowait(envelope)
            except asyncio.QueueFull:
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    continue
                try:
                    queue.put_nowait(envelope)
                except asyncio.QueueFull:
                    continue
        return envelope

    async def subscribe(
        self, *, conversation_id: str | None = None, run_id: str | None = None
    ) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=100)
        async with self._lock:
            if conversation_id is not None:
                self._conversation_subscribers[conversation_id].add(queue)
            if run_id is not None:
                self._run_subscribers[run_id].add(queue)
        return queue

    async def unsubscribe(
        self,
        queue: asyncio.Queue[dict[str, Any]],
        *,
        conversation_id: str | None = None,
        run_id: str | None = None,
    ) -> None:
        async with self._lock:
            if conversation_id is not None:
                self._conversation_subscribers.get(conversation_id, set()).discard(queue)
            if run_id is not None:
                self._run_subscribers.get(run_id, set()).discard(queue)
