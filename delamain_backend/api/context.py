from __future__ import annotations

import hashlib
import shutil
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query

from delamain_backend.agent.context import context_items_for_run
from delamain_backend.api.audit import audit_event
from delamain_backend.api.deps import get_bus, get_config, get_db
from delamain_backend.config import AppConfig
from delamain_backend.db import Database
from delamain_backend.events import EventBus
from delamain_backend.schemas import ContextFilePatch

router = APIRouter(tags=["context"])

CONTEXT_FILES = {
    "system-context": "system_context",
    "short-term-continuity": "short_term_continuity",
}


@router.get("/context/current")
async def get_current_context(
    context_mode: str = Query("normal"),
    config: AppConfig = Depends(get_config),
):
    if context_mode not in {"normal", "blank_slate"}:
        raise HTTPException(status_code=400, detail="Invalid context_mode")
    return {"context_mode": context_mode, "items": context_items_for_run(config, context_mode)}


@router.get("/context/files/{file_id}")
async def get_context_file(file_id: str, config: AppConfig = Depends(get_config)):
    path, mode = _context_file(config, file_id)
    if not path.exists():
        return {
            "id": file_id,
            "mode": mode,
            "path": str(path),
            "exists": False,
            "content": "",
            "byte_count": 0,
            "sha256": None,
        }
    content = path.read_text(encoding="utf-8")
    data = content.encode("utf-8")
    return {
        "id": file_id,
        "mode": mode,
        "path": str(path),
        "exists": True,
        "content": content,
        "byte_count": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


@router.patch("/context/files/{file_id}")
async def patch_context_file(
    file_id: str,
    payload: ContextFilePatch,
    config: AppConfig = Depends(get_config),
    db: Database = Depends(get_db),
    bus: EventBus = Depends(get_bus),
):
    path, mode = _context_file(config, file_id)
    _ensure_context_path_allowed(config, path)
    backup_path = _backup_context_file(config, file_id, path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload.content, encoding="utf-8")
    data = payload.content.encode("utf-8")
    await audit_event(
        db=db,
        bus=bus,
        conversation_id=payload.conversation_id,
        action="context.file_updated",
        summary=f"Context file updated: {file_id}",
        payload={
            "file_id": file_id,
            "mode": mode,
            "path": str(path),
            "backup_path": str(backup_path) if backup_path else None,
            "byte_count": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        },
    )
    return await get_context_file(file_id, config)


def _context_file(config: AppConfig, file_id: str) -> tuple[Path, str]:
    if file_id == "system-context":
        return config.paths.system_context, "system_context"
    if file_id == "short-term-continuity":
        return config.paths.short_term_continuity, "short_term_continuity"
    raise HTTPException(status_code=404, detail="Context file not found")


def _ensure_context_path_allowed(config: AppConfig, path: Path) -> None:
    resolved = path.expanduser().resolve(strict=False)
    workspace = config.paths.llm_workspace.expanduser().resolve(strict=False)
    sensitive = config.paths.sensitive.expanduser().resolve(strict=False)
    if resolved != workspace and workspace not in resolved.parents:
        raise HTTPException(status_code=403, detail="Context file is outside llm-workspace")
    if resolved == sensitive or sensitive in resolved.parents:
        raise HTTPException(status_code=403, detail="Context file cannot be under Sensitive")


def _backup_context_file(config: AppConfig, file_id: str, path: Path) -> Path | None:
    backup_root = config.database.path.parent / "context-backups"
    for root in (config.paths.vault, config.paths.llm_workspace, config.paths.sensitive):
        resolved_backup = backup_root.expanduser().resolve(strict=False)
        resolved_root = root.expanduser().resolve(strict=False)
        if resolved_backup == resolved_root or resolved_root in resolved_backup.parents:
            raise HTTPException(status_code=500, detail="Context backup root is under a synced root")
    if not path.exists():
        return None
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_dir = backup_root / file_id
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"{timestamp}-{path.name}.bak"
    shutil.copy2(path, backup_path)
    return backup_path
