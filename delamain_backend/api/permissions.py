from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from delamain_backend.api.deps import get_bus, get_db
from delamain_backend.db import Database
from delamain_backend.events import EventBus
from delamain_backend.schemas import PermissionResolve

router = APIRouter(tags=["permissions"])


@router.get("/runs/{run_id}/permissions")
async def list_run_permissions(run_id: str, db: Database = Depends(get_db)):
    run = await db.fetchone("SELECT id FROM runs WHERE id = ?", (run_id,))
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    rows = await db.fetchall(
        "SELECT * FROM permissions WHERE run_id = ? ORDER BY created_at",
        (run_id,),
    )
    return [_permission_out(row) for row in rows]


@router.post("/permissions/{permission_id}/resolve")
async def resolve_permission(
    permission_id: str,
    payload: PermissionResolve,
    db: Database = Depends(get_db),
    bus: EventBus = Depends(get_bus),
):
    row = await db.fetchone("SELECT * FROM permissions WHERE id = ?", (permission_id,))
    if row is None:
        raise HTTPException(status_code=404, detail="Permission not found")
    if row["status"] != "pending":
        return _permission_out(row)
    if payload.decision not in {"approved", "denied"}:
        raise HTTPException(status_code=400, detail="decision must be approved or denied")
    await db.execute(
        """
        UPDATE permissions
        SET status = ?,
            decision = ?,
            note = ?,
            resolver = ?,
            resolved_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
        WHERE id = ?
        """,
        (
            "resolved",
            payload.decision,
            payload.note,
            payload.resolver or "user",
            permission_id,
        ),
    )
    updated = await db.fetchone("SELECT * FROM permissions WHERE id = ?", (permission_id,))
    await bus.emit(
        conversation_id=updated["conversation_id"],
        run_id=updated["run_id"],
        event_type="permission.resolved",
        payload={
            "permission_id": permission_id,
            "decision": payload.decision,
            "resolver": payload.resolver or "user",
            "note": payload.note,
        },
    )
    return _permission_out(updated)


def _permission_out(row: dict) -> dict:
    return dict(row)
