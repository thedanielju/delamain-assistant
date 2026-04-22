from __future__ import annotations

from delamain_backend.db import Database
from delamain_backend.events import EventBus

SYSTEM_AUDIT_CONVERSATION_ID = "conv_system"


async def audit_event(
    *,
    db: Database,
    bus: EventBus,
    conversation_id: str | None,
    action: str,
    summary: str,
    payload: dict | None = None,
) -> None:
    target = conversation_id or SYSTEM_AUDIT_CONVERSATION_ID
    if conversation_id is None:
        await db.execute(
            """
            INSERT OR IGNORE INTO conversations(id, title, archived)
            VALUES (?, 'System audit', 1)
            """,
            (SYSTEM_AUDIT_CONVERSATION_ID,),
        )
    else:
        existing = await db.fetchone("SELECT id FROM conversations WHERE id = ?", (target,))
        if existing is None:
            target = SYSTEM_AUDIT_CONVERSATION_ID
            await db.execute(
                """
                INSERT OR IGNORE INTO conversations(id, title, archived)
                VALUES (?, 'System audit', 1)
                """,
                (SYSTEM_AUDIT_CONVERSATION_ID,),
            )
    event_payload = {"action": action, "summary": summary}
    if payload:
        event_payload.update(payload)
    await bus.emit(
        conversation_id=target,
        run_id=None,
        event_type="audit",
        payload=event_payload,
    )
