from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse

from delamain_backend.api.deps import get_config, get_db
from delamain_backend.config import AppConfig
from delamain_backend.db import Database

router = APIRouter(tags=["action-runs"])


@router.get("/action-runs/{action_run_id}")
async def get_action_run(action_run_id: str, db: Database = Depends(get_db)):
    row = await _get_action_run(db, action_run_id)
    return _action_run_out(row)


@router.get("/action-runs/{action_run_id}/stdout", response_class=PlainTextResponse)
async def get_action_stdout(
    action_run_id: str,
    config: AppConfig = Depends(get_config),
    db: Database = Depends(get_db),
):
    row = await _get_action_run(db, action_run_id)
    return _read_owned_artifact(config, row, "stdout_path")


@router.get("/action-runs/{action_run_id}/stderr", response_class=PlainTextResponse)
async def get_action_stderr(
    action_run_id: str,
    config: AppConfig = Depends(get_config),
    db: Database = Depends(get_db),
):
    row = await _get_action_run(db, action_run_id)
    return _read_owned_artifact(config, row, "stderr_path")


@router.get("/conversations/{conversation_id}/action-runs")
async def list_conversation_action_runs(
    conversation_id: str, db: Database = Depends(get_db)
):
    conversation = await db.fetchone("SELECT id FROM conversations WHERE id = ?", (conversation_id,))
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    rows = await db.fetchall(
        """
        SELECT *
        FROM action_runs
        WHERE conversation_id = ?
        ORDER BY created_at DESC
        """,
        (conversation_id,),
    )
    return [_action_run_out(row) for row in rows]


async def _get_action_run(db: Database, action_run_id: str) -> dict:
    row = await db.fetchone("SELECT * FROM action_runs WHERE id = ?", (action_run_id,))
    if row is None:
        raise HTTPException(status_code=404, detail="Action run not found")
    return row


def _read_owned_artifact(config: AppConfig, row: dict, field: str) -> str:
    output_root = (config.database.path.parent / "action-outputs").resolve(strict=False)
    path = Path(row[field]).expanduser().resolve(strict=False)
    try:
        path.relative_to(output_root)
    except ValueError:
        raise HTTPException(status_code=403, detail="Artifact path is outside action output root")
    if path == output_root:
        raise HTTPException(status_code=403, detail="Artifact path must be a file")
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Artifact not found")
    return path.read_text(encoding="utf-8", errors="replace")


def _action_run_out(row: dict) -> dict:
    return {
        **row,
        "writes": bool(row["writes"]),
        "remote": bool(row["remote"]),
    }
