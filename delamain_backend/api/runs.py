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
