from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from delamain_backend.agent.runner import new_id
from delamain_backend.db import Database
from delamain_backend.api.deps import get_db
from delamain_backend.schemas import FolderCreate, FolderUpdate

router = APIRouter(tags=["folders"])


@router.get("/folders")
async def list_folders(db: Database = Depends(get_db)):
    rows = await db.fetchall("SELECT * FROM folders ORDER BY name COLLATE NOCASE")
    return [_folder_out(row) for row in rows]


@router.post("/folders", status_code=status.HTTP_201_CREATED)
async def create_folder(payload: FolderCreate, db: Database = Depends(get_db)):
    if payload.parent_id is not None:
        await _require_folder(db, payload.parent_id)
    folder_id = new_id("folder")
    await db.execute(
        """
        INSERT INTO folders(id, name, parent_id)
        VALUES (?, ?, ?)
        """,
        (folder_id, payload.name, payload.parent_id),
    )
    return _folder_out(await _require_folder(db, folder_id))


@router.patch("/folders/{folder_id}")
async def update_folder(
    folder_id: str,
    payload: FolderUpdate,
    db: Database = Depends(get_db),
):
    row = await _require_folder(db, folder_id)
    payload_fields = (
        payload.model_fields_set if hasattr(payload, "model_fields_set") else payload.__fields_set__
    )
    parent_id = payload.parent_id if "parent_id" in payload_fields else row["parent_id"]
    if parent_id == folder_id:
        raise HTTPException(status_code=400, detail="Folder cannot be its own parent")
    if parent_id is not None:
        await _require_folder(db, parent_id)
    name = row["name"] if payload.name is None else payload.name
    await db.execute(
        """
        UPDATE folders
        SET name = ?,
            parent_id = ?,
            updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
        WHERE id = ?
        """,
        (name, parent_id, folder_id),
    )
    return _folder_out(await _require_folder(db, folder_id))


@router.delete("/folders/{folder_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_folder(folder_id: str, db: Database = Depends(get_db)):
    await _require_folder(db, folder_id)
    await db.execute_transaction(
        [
            ("UPDATE conversations SET folder_id = NULL WHERE folder_id = ?", (folder_id,)),
            ("UPDATE folders SET parent_id = NULL WHERE parent_id = ?", (folder_id,)),
            ("DELETE FROM folders WHERE id = ?", (folder_id,)),
        ]
    )
    return None


async def _require_folder(db: Database, folder_id: str) -> dict:
    row = await db.fetchone("SELECT * FROM folders WHERE id = ?", (folder_id,))
    if row is None:
        raise HTTPException(status_code=404, detail="Folder not found")
    return row


def _folder_out(row: dict) -> dict:
    return dict(row)
