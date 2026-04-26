from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from delamain_backend.agent.runner import new_id
from delamain_backend.api.deps import get_bus, get_db, get_run_manager
from delamain_backend.db import Database
from delamain_backend.events import EventBus

router = APIRouter(tags=["runs"])


@router.get("/runs/{run_id}")
async def get_run(run_id: str, db: Database = Depends(get_db)):
    row = await db.fetchone("SELECT * FROM runs WHERE id = ?", (run_id,))
    if row is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return {**row, "incognito_route": bool(row["incognito_route"])}


@router.post("/runs/{run_id}/cancel")
async def cancel_run(
    run_id: str,
    db: Database = Depends(get_db),
    bus: EventBus = Depends(get_bus),
):
    row = await db.fetchone("SELECT * FROM runs WHERE id = ?", (run_id,))
    if row is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if row["status"] in {"completed", "failed", "cancelled", "interrupted"}:
        return {**row, "incognito_route": bool(row["incognito_route"])}
    pending_permissions = await db.fetchall(
        """
        SELECT id
        FROM permissions
        WHERE run_id = ?
          AND status = 'pending'
        ORDER BY created_at
        """,
        (run_id,),
    )
    started_tools = await db.fetchall(
        """
        SELECT id
        FROM tool_calls
        WHERE run_id = ?
          AND status = 'started'
        ORDER BY created_at
        """,
        (run_id,),
    )
    assistant_message_id = row["assistant_message_id"]
    for permission in pending_permissions:
        await db.execute(
            """
            UPDATE permissions
            SET status = 'resolved',
                decision = 'denied',
                resolver = 'system',
                note = 'Run cancelled while awaiting approval',
                resolved_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            WHERE id = ?
            """,
            (permission["id"],),
        )
        await bus.emit(
            conversation_id=row["conversation_id"],
            run_id=run_id,
            event_type="permission.resolved",
            payload={
                "run_id": run_id,
                "permission_id": permission["id"],
                "decision": "denied",
                "resolver": "system",
                "note": "Run cancelled while awaiting approval",
            },
        )
    for tool in started_tools:
        await db.execute(
            """
            UPDATE tool_calls
            SET status = 'cancelled',
                error_message = 'Run cancelled',
                completed_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            WHERE id = ?
            """,
            (tool["id"],),
        )
        if assistant_message_id:
            await bus.emit(
                conversation_id=row["conversation_id"],
                run_id=run_id,
                event_type="tool.finished",
                payload={
                    "tool_call_id": tool["id"],
                    "assistant_message_id": assistant_message_id,
                    "status": "cancelled",
                    "duration_ms": 0,
                    "result_summary": "Run cancelled",
                    "stdout": "",
                    "stderr": "Run cancelled",
                },
            )
    await db.execute(
        """
        UPDATE runs
        SET status = 'cancelled',
            completed_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
        WHERE id = ?
        """,
        (run_id,),
    )
    updated = await db.fetchone("SELECT * FROM runs WHERE id = ?", (run_id,))
    await bus.emit(
        conversation_id=updated["conversation_id"],
        run_id=run_id,
        event_type="error",
        payload={"code": "RUN_CANCELLED", "message": "Run cancelled", "details": None},
    )
    await bus.emit(
        conversation_id=updated["conversation_id"],
        run_id=run_id,
        event_type="run.completed",
        payload={"run_id": run_id, "status": "cancelled"},
    )
    return {**updated, "incognito_route": bool(updated["incognito_route"])}


@router.post("/runs/{run_id}/retry", status_code=status.HTTP_202_ACCEPTED)
async def retry_run(
    run_id: str,
    db: Database = Depends(get_db),
    run_manager=Depends(get_run_manager),
):
    row = await db.fetchone("SELECT * FROM runs WHERE id = ?", (run_id,))
    if row is None:
        raise HTTPException(status_code=404, detail="Run not found")
    new_run_id = new_id("run")
    await db.execute(
        """
        INSERT INTO runs(
            id, conversation_id, user_message_id, status,
            context_mode, model_route, incognito_route
        )
        VALUES (?, ?, ?, 'queued', ?, ?, ?)
        """,
        (
            new_run_id,
            row["conversation_id"],
            row["user_message_id"],
            row["context_mode"],
            row["model_route"],
            row["incognito_route"],
        ),
    )
    await run_manager.bus.emit(
        conversation_id=row["conversation_id"],
        run_id=new_run_id,
        event_type="run.queued",
        payload={"run_id": new_run_id, "position": 1},
    )
    run_manager.enqueue(new_run_id)
    return {"run_id": new_run_id, "status": "queued"}
