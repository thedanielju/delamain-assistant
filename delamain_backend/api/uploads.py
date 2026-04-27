from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse

from delamain_backend.api.deps import get_config, get_db
from delamain_backend.config import AppConfig
from delamain_backend.db import Database
from delamain_backend.schemas import UploadPromoteRequest
from delamain_backend.uploads import (
    UploadError,
    clear_uploads,
    create_upload_from_bytes,
    delete_upload,
    ensure_upload_content,
    get_upload,
    list_uploads,
    parse_single_file_multipart,
    preview_upload,
    promote_upload,
    upload_row_out,
)

router = APIRouter(tags=["uploads"])


@router.post("/uploads", status_code=status.HTTP_201_CREATED)
async def create_upload(
    request: Request,
    config: AppConfig = Depends(get_config),
    db: Database = Depends(get_db),
):
    try:
        parsed = await parse_single_file_multipart(
            request,
            max_file_size=config.uploads.max_size_bytes,
        )
        return await create_upload_from_bytes(
            db,
            config,
            filename=parsed.filename,
            data=parsed.data,
            mime_type=parsed.content_type,
        )
    except UploadError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.get("/uploads")
async def get_uploads(db: Database = Depends(get_db)):
    return {"uploads": await list_uploads(db)}


@router.delete("/uploads")
async def clear_pending_uploads(
    config: AppConfig = Depends(get_config),
    db: Database = Depends(get_db),
):
    return await clear_uploads(db, config)


@router.post("/uploads/clear")
async def clear_pending_uploads_compat(
    config: AppConfig = Depends(get_config),
    db: Database = Depends(get_db),
):
    return await clear_uploads(db, config)


@router.get("/uploads/{upload_id}")
async def get_upload_detail(upload_id: str, db: Database = Depends(get_db)):
    row = await get_upload(db, upload_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Upload not found")
    return upload_row_out(row)


@router.get("/uploads/{upload_id}/download")
async def download_upload(upload_id: str, db: Database = Depends(get_db)):
    row = await get_upload(db, upload_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Upload not found")
    path = Path(row["storage_path"])
    if not path.exists():
        raise HTTPException(status_code=404, detail="Stored upload is missing")
    return FileResponse(
        path,
        media_type=row.get("mime_type") or "application/octet-stream",
        filename=row["original_filename"],
    )


@router.get("/uploads/{upload_id}/preview")
async def get_upload_preview(
    upload_id: str,
    limit: int | None = Query(default=None, ge=1, le=100000),
    config: AppConfig = Depends(get_config),
    db: Database = Depends(get_db),
):
    try:
        return await preview_upload(db, config, upload_id, limit=limit)
    except UploadError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.post("/uploads/{upload_id}/convert")
async def convert_upload(
    upload_id: str,
    config: AppConfig = Depends(get_config),
    db: Database = Depends(get_db),
):
    try:
        row = await ensure_upload_content(db, config, upload_id, force=True)
    except UploadError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return upload_row_out(row)


@router.post("/uploads/{upload_id}/promote")
async def promote_upload_endpoint(
    upload_id: str,
    payload: UploadPromoteRequest,
    config: AppConfig = Depends(get_config),
    db: Database = Depends(get_db),
):
    try:
        return await promote_upload(db, config, upload_id, category=payload.category)
    except UploadError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.delete("/uploads/{upload_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_upload_endpoint(
    upload_id: str,
    config: AppConfig = Depends(get_config),
    db: Database = Depends(get_db),
):
    deleted = await delete_upload(db, config, upload_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Upload not found")
    return None
