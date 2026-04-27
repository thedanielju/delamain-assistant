from __future__ import annotations

import asyncio
import hashlib
import json
import mimetypes
import shutil
import uuid
from dataclasses import dataclass
from email import policy
from email.parser import BytesParser
from pathlib import Path
from typing import Any

from starlette.requests import Request

from delamain_backend.config import AppConfig
from delamain_backend.db import Database
from delamain_ref.converters import build_metadata_payload, convert_rich_document
from delamain_ref.ingest import ensure_bundle
from delamain_ref.paths import RuntimePaths, ensure_base_layout
from delamain_ref.util import atomic_write_json, atomic_write_text, sha256_file
from delamain_ref.vault_index import build_vault_index

SUPPORTED_UPLOAD_EXTENSIONS = {".pdf", ".docx", ".rtf", ".odt", ".txt", ".md"}
TEXT_UPLOAD_EXTENSIONS = {".txt", ".md"}
RICH_UPLOAD_EXTENSIONS = {".pdf", ".docx", ".rtf", ".odt"}
REJECTED_KIND_EXTENSIONS = {
    ".7z",
    ".app",
    ".bat",
    ".bin",
    ".bz2",
    ".cmd",
    ".com",
    ".dmg",
    ".dll",
    ".exe",
    ".gz",
    ".iso",
    ".js",
    ".msi",
    ".pkg",
    ".ps1",
    ".rar",
    ".sh",
    ".tar",
    ".tgz",
    ".vbs",
    ".xz",
    ".zip",
}
MULTIPART_OVERHEAD_BYTES = 2 * 1024 * 1024


class UploadError(ValueError):
    def __init__(self, message: str, *, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class ParsedUpload:
    filename: str
    content_type: str | None
    data: bytes


def new_upload_id() -> str:
    return f"upl_{uuid.uuid4().hex}"


def validate_upload_storage_root(config: AppConfig) -> Path:
    root = config.uploads.storage_path.expanduser().resolve(strict=False)
    forbidden = [
        config.paths.vault,
        config.paths.sensitive,
        config.paths.llm_workspace,
    ]
    for item in forbidden:
        resolved = item.expanduser().resolve(strict=False)
        if root == resolved or resolved in root.parents:
            raise UploadError(
                "Upload storage root must be outside vault, Sensitive, and llm-workspace",
                status_code=500,
            )
    return root


async def parse_single_file_multipart(
    request: Request,
    *,
    max_file_size: int,
) -> ParsedUpload:
    content_type = request.headers.get("content-type", "")
    if "multipart/form-data" not in content_type.lower():
        raise UploadError("Expected multipart/form-data")
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            declared_length = int(content_length)
        except ValueError:
            declared_length = 0
        if declared_length > max_file_size + MULTIPART_OVERHEAD_BYTES:
            raise UploadError("Upload is too large", status_code=413)

    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > max_file_size + MULTIPART_OVERHEAD_BYTES:
            raise UploadError("Upload is too large", status_code=413)
        chunks.append(chunk)
    body = b"".join(chunks)
    message = BytesParser(policy=policy.default).parsebytes(
        b"Content-Type: " + content_type.encode("latin-1") + b"\r\n"
        b"MIME-Version: 1.0\r\n\r\n"
        + body
    )
    if not message.is_multipart():
        raise UploadError("Invalid multipart body")

    for part in message.iter_parts():
        disposition = part.get("content-disposition", "")
        if "form-data" not in disposition:
            continue
        if part.get_param("name", header="content-disposition") != "file":
            continue
        filename = part.get_filename()
        if not filename:
            raise UploadError("Multipart file part is missing filename")
        data = part.get_payload(decode=True) or b""
        if len(data) > max_file_size:
            raise UploadError("Upload is too large", status_code=413)
        return ParsedUpload(
            filename=filename,
            content_type=part.get_content_type(),
            data=data,
        )
    raise UploadError("Multipart body must include a file part named 'file'")


def validate_upload_filename(filename: str) -> tuple[str, str]:
    name = filename.strip()
    if not name or name in {".", ".."}:
        raise UploadError("Upload filename is required")
    if "/" in name or "\\" in name or "\x00" in name:
        raise UploadError("Upload filename must not contain path separators")
    if any(ord(ch) < 32 for ch in name):
        raise UploadError("Upload filename contains control characters")
    if len(name.encode("utf-8")) > 240:
        raise UploadError("Upload filename is too long")
    path = Path(name)
    if path.name != name or ".." in path.parts:
        raise UploadError("Upload filename must not contain traversal")
    extension = path.suffix.lower()
    if extension in REJECTED_KIND_EXTENSIONS:
        raise UploadError("Executable and archive uploads are not supported", status_code=415)
    if extension not in SUPPORTED_UPLOAD_EXTENSIONS:
        supported = ", ".join(sorted(SUPPORTED_UPLOAD_EXTENSIONS))
        raise UploadError(f"Unsupported upload extension `{extension}`. Supported: {supported}.", status_code=415)
    return name, extension


async def create_upload_from_bytes(
    db: Database,
    config: AppConfig,
    *,
    filename: str,
    data: bytes,
    mime_type: str | None,
) -> dict[str, Any]:
    safe_name, extension = validate_upload_filename(filename)
    if len(data) > config.uploads.max_size_bytes:
        raise UploadError("Upload is too large", status_code=413)
    if extension in TEXT_UPLOAD_EXTENSIONS and b"\x00" in data:
        raise UploadError("Text upload appears to contain binary data", status_code=415)

    upload_id = new_upload_id()
    storage_root = validate_upload_storage_root(config)
    upload_root = storage_root / upload_id
    original_dir = upload_root / "original"
    original_dir.mkdir(parents=True, exist_ok=True)
    original_path = original_dir / safe_name
    tmp_path = original_path.with_name(f"{original_path.name}.tmp")
    tmp_path.write_bytes(data)
    tmp_path.replace(original_path)
    digest = hashlib.sha256(data).hexdigest()

    await db.execute(
        """
        INSERT INTO uploads(
            id, original_filename, extension, mime_type, byte_count, sha256,
            storage_path, conversion_status
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')
        """,
        (
            upload_id,
            safe_name,
            extension,
            mime_type,
            len(data),
            digest,
            str(original_path),
        ),
    )
    await ensure_upload_content(db, config, upload_id)
    row = await get_upload(db, upload_id)
    assert row is not None
    return upload_row_out(row)


async def get_upload(db: Database, upload_id: str) -> dict[str, Any] | None:
    return await db.fetchone("SELECT * FROM uploads WHERE id = ?", (upload_id,))


async def list_uploads(db: Database) -> list[dict[str, Any]]:
    rows = await db.fetchall("SELECT * FROM uploads ORDER BY created_at DESC")
    return [upload_row_out(row) for row in rows]


def upload_row_out(row: dict[str, Any]) -> dict[str, Any]:
    conversion_status = str(row.get("conversion_status") or "pending")
    promoted_category = row.get("promoted_category")
    promoted_bundle_id = row.get("promoted_bundle_id")
    promoted_path = (
        f"{promoted_category}/{promoted_bundle_id}"
        if promoted_category and promoted_bundle_id
        else None
    )
    if row.get("promoted_at"):
        status = "promoted"
    elif conversion_status == "failed":
        status = "failed"
    elif conversion_status in {"fresh", "needs_ocr"}:
        status = "converted"
    else:
        status = conversion_status
    return {
        "id": row["id"],
        "original_filename": row["original_filename"],
        "extension": row.get("extension"),
        "mime_type": row.get("mime_type"),
        "sha256": row.get("sha256"),
        "conversion_status": conversion_status,
        "conversion_error": row.get("conversion_error"),
        "conversion_converter": row.get("conversion_converter"),
        "promoted_category": promoted_category,
        "promoted_bundle_id": promoted_bundle_id,
        "promoted_at": row.get("promoted_at"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "expires_at": row.get("expires_at"),
        "filename": row["original_filename"],
        "name": row["original_filename"],
        "content_type": row.get("mime_type"),
        "size": int(row["byte_count"]),
        "byte_count": int(row["byte_count"]),
        "status": status,
        "preview_status": "preview_ready" if status in {"converted", "promoted"} else status,
        "error_message": row.get("conversion_error"),
        "category": promoted_category,
        "promoted_path": promoted_path,
        "promoted": bool(row.get("promoted_at")),
    }


async def ensure_upload_content(
    db: Database,
    config: AppConfig,
    upload_id: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    row = await get_upload(db, upload_id)
    if row is None:
        raise UploadError("Upload not found", status_code=404)
    try:
        result = await asyncio.to_thread(_ensure_upload_content_sync, config, row, force)
    except UploadError:
        raise
    except Exception as exc:
        result = {
            "status": "failed",
            "converter": None,
            "extracted_path": row.get("extracted_path"),
            "converted_path": row.get("converted_path"),
            "error": f"{type(exc).__name__}: {exc}",
        }
    await db.execute(
        """
        UPDATE uploads
        SET extracted_path = ?,
            converted_path = ?,
            conversion_status = ?,
            converter = ?,
            conversion_error = ?,
            updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
        WHERE id = ?
        """,
        (
            result.get("extracted_path"),
            result.get("converted_path"),
            result["status"],
            result.get("converter"),
            result.get("error"),
            upload_id,
        ),
    )
    updated = await get_upload(db, upload_id)
    assert updated is not None
    return updated


def _ensure_upload_content_sync(
    config: AppConfig,
    row: dict[str, Any],
    force: bool,
) -> dict[str, Any]:
    original_path = Path(row["storage_path"])
    if not original_path.exists():
        raise UploadError("Stored original is missing", status_code=404)
    extension = str(row["extension"]).lower()
    cache_root = original_path.parents[1] / "cache"
    cache_root.mkdir(parents=True, exist_ok=True)

    if extension in TEXT_UPLOAD_EXTENSIONS:
        extracted_path = cache_root / "document.md"
        if not force and extracted_path.exists():
            return {
                "status": "fresh",
                "converter": "direct_text",
                "extracted_path": str(extracted_path),
                "converted_path": None,
                "error": None,
            }
        text = original_path.read_text(encoding="utf-8", errors="replace")
        atomic_write_text(extracted_path, text)
        return {
            "status": "fresh",
            "converter": "direct_text",
            "extracted_path": str(extracted_path),
            "converted_path": None,
            "error": None,
        }

    if extension in RICH_UPLOAD_EXTENSIONS:
        converted_path = cache_root / "document.md"
        if not force and converted_path.exists() and row.get("conversion_status") not in {"failed", "pending"}:
            return {
                "status": row.get("conversion_status") or "fresh",
                "converter": row.get("converter"),
                "extracted_path": None,
                "converted_path": str(converted_path),
                "error": row.get("conversion_error"),
            }
        figures_dir = cache_root / "figures"
        conversion = convert_rich_document(original_path, figures_dir)
        metadata = build_metadata_payload(
            source_name=original_path.name,
            source_size=original_path.stat().st_size,
            source_sha256=sha256_file(original_path),
            source_mtime=_file_mtime_iso(original_path),
            converter=conversion.converter,
            status=conversion.status,
            warnings=conversion.warnings,
            extraction_report=conversion.extraction_report,
        )
        atomic_write_json(cache_root / "metadata.json", metadata)
        atomic_write_json(cache_root / "extraction.json", conversion.extraction_report)
        if conversion.ok:
            atomic_write_text(converted_path, conversion.markdown)
            return {
                "status": conversion.status,
                "converter": conversion.converter,
                "extracted_path": None,
                "converted_path": str(converted_path),
                "error": None,
            }
        return {
            "status": "failed",
            "converter": conversion.converter,
            "extracted_path": None,
            "converted_path": None,
            "error": conversion.error or "Conversion failed",
        }

    raise UploadError("Unsupported upload extension", status_code=415)


async def preview_upload(
    db: Database,
    config: AppConfig,
    upload_id: str,
    *,
    limit: int | None = None,
) -> dict[str, Any]:
    row = await ensure_upload_content(db, config, upload_id)
    content_path = upload_content_path(row)
    if content_path is None or not content_path.exists():
        raise UploadError("Upload has no extracted preview", status_code=409)
    text = content_path.read_text(encoding="utf-8", errors="replace")
    char_limit = max(1, min(limit or config.uploads.preview_char_limit, 100000))
    content = text[:char_limit]
    upload = upload_row_out(row)
    return {
        "upload": upload,
        "upload_id": row["id"],
        "status": upload["status"],
        "filename": row["original_filename"],
        "content_type": row.get("mime_type"),
        "size": int(row["byte_count"]),
        "content": content,
        "text_preview": content,
        "markdown_preview": content,
        "extracted_text": content,
        "truncated": len(text) > char_limit,
        "char_count": min(len(text), char_limit),
        "total_char_count": len(text),
        "token_estimate": max(1, len(content) // 4) if content else 0,
        "metadata": {
            "truncated": len(text) > char_limit,
            "char_count": min(len(text), char_limit),
            "total_char_count": len(text),
            "converter": row.get("converter"),
        },
        "error_message": row.get("conversion_error"),
    }


def upload_content_path(row: dict[str, Any]) -> Path | None:
    raw = row.get("converted_path") or row.get("extracted_path")
    return Path(raw) if raw else None


def _content_mime_type(row: dict[str, Any]) -> str:
    explicit = row.get("mime_type")
    if explicit:
        return str(explicit)
    guessed, _ = mimetypes.guess_type(str(row.get("original_filename") or ""))
    return guessed or "application/octet-stream"


async def attachment_records_for_prompt(
    db: Database,
    config: AppConfig,
    attachments: list[Any],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for attachment in attachments:
        upload_id = str(attachment.upload_id)
        if upload_id in seen:
            raise UploadError(f"Duplicate upload attachment: {upload_id}", status_code=422)
        seen.add(upload_id)
        row = await get_upload(db, upload_id)
        if row is None:
            raise UploadError(f"Upload not found: {upload_id}", status_code=404)
        included = bool(attachment.include)
        if included:
            row = await ensure_upload_content(db, config, upload_id)
            original_path = Path(row["storage_path"])
            native_context = (
                attachment.representation == "rich"
                and str(row["extension"]).lower() in RICH_UPLOAD_EXTENSIONS
                and original_path.exists()
                and int(row["byte_count"]) <= config.uploads.native_file_max_size_bytes
            )
            content_path = upload_content_path(row)
            if (content_path is None or not content_path.exists()) and not native_context:
                raise UploadError(
                    f"Upload is not convertible for run context: {row['original_filename']}",
                    status_code=422,
                )
            if content_path is not None and content_path.exists():
                content_sha = sha256_file(content_path)
                text = content_path.read_text(encoding="utf-8", errors="replace")
                context_chars = min(len(text), config.uploads.context_char_limit)
            else:
                content_sha = None
                context_chars = 0
        else:
            content_path = upload_content_path(row)
            content_sha = sha256_file(content_path) if content_path and content_path.exists() else None
            context_chars = 0
            original_path = Path(row["storage_path"])
            native_context = False
        records.append(
            {
                "upload_id": upload_id,
                "original_filename": row["original_filename"],
                "representation": attachment.representation,
                "included": included,
                "byte_count": int(row["byte_count"]),
                "sha256": row["sha256"],
                "original_path": str(original_path),
                "content_path": str(content_path) if content_path else None,
                "content_sha256": content_sha,
                "context_char_count": context_chars,
                "mime_type": _content_mime_type(row),
                "extension": row["extension"],
                "native_context": native_context,
            }
        )
    return records


async def run_attachment_context(
    db: Database,
    config: AppConfig,
    run_id: str,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    rows = await db.fetchall(
        """
        SELECT *
        FROM run_upload_attachments
        WHERE run_id = ?
        ORDER BY created_at ASC
        """,
        (run_id,),
    )
    items: list[dict[str, Any]] = []
    messages: list[dict[str, str]] = []
    total_limit = config.uploads.context_char_limit
    remaining = total_limit
    for row in rows:
        included = bool(row["included"])
        content_path = Path(row["content_path"]) if row.get("content_path") else None
        native_context = bool(row.get("native_context"))
        missing = (
            included
            and not native_context
            and (content_path is None or not content_path.exists())
        )
        text = ""
        fallback_text = ""
        if included and not missing and remaining > 0:
            if content_path is not None and content_path.exists():
                text = content_path.read_text(encoding="utf-8", errors="replace")
                text = text[:remaining]
                fallback_text = text
                remaining -= len(text)
        original_path = Path(row["original_path"]) if row.get("original_path") else None
        native_missing = (
            included
            and native_context
            and (original_path is None or not original_path.exists())
        )
        item = {
            "path": f"upload:{row['upload_id'] or row['id']}",
            "mode": "upload_attachment",
            "included": included and not missing and not native_missing and (
                bool(text) or native_context
            ),
            "missing": missing or native_missing,
            "byte_count": row["byte_count"],
            "sha256": row["content_sha256"] or row["sha256"],
            "title": row["original_filename"],
            "upload_id": row["upload_id"],
            "representation": row["representation"],
            "native_context": native_context,
            "context_char_count": len(text),
        }
        items.append(item)
        if item["included"] and native_context and original_path is not None:
            messages.append(
                {
                    "role": "user",
                    "content": _native_attachment_content_parts(
                        row,
                        original_path,
                        fallback_text,
                    ),
                }
            )
        elif item["included"]:
            messages.append(
                {
                    "role": "system",
                    "content": _attachment_context_message(row, text),
                }
            )
    return items, messages


async def promote_upload(
    db: Database,
    config: AppConfig,
    upload_id: str,
    *,
    category: str,
) -> dict[str, Any]:
    row = await get_upload(db, upload_id)
    if row is None:
        raise UploadError("Upload not found", status_code=404)
    if category not in {"reference", "syllabi"}:
        raise UploadError("Unsupported promotion category", status_code=422)
    result = await asyncio.to_thread(_promote_upload_sync, config, row, category)
    bundle = result.get("bundle") or {}
    await db.execute(
        """
        UPDATE uploads
        SET promoted_category = ?,
            promoted_bundle_id = ?,
            promoted_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
            updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
        WHERE id = ?
        """,
        (category, bundle.get("id"), upload_id),
    )
    updated = await get_upload(db, upload_id)
    return {
        "upload": upload_row_out(updated) if updated else None,
        "ensure": result,
    }


def _promote_upload_sync(config: AppConfig, row: dict[str, Any], category: str) -> dict[str, Any]:
    paths = _runtime_paths(config)
    ensure_base_layout(paths)
    original = Path(row["storage_path"])
    if not original.exists():
        raise UploadError("Stored original is missing", status_code=404)
    destination = _non_colliding_path(paths.category_root(category) / row["original_filename"])
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(original, destination)
    result = ensure_bundle(paths, str(destination), category=category)
    if not result.get("ok"):
        destination.unlink(missing_ok=True)
        raise UploadError(
            "Promotion conversion failed: " + "; ".join(result.get("errors") or ["unknown error"]),
            status_code=422,
        )
    index_result = build_vault_index(paths, auto_ingest=False)
    return {
        **result,
        "vault_index": {
            "ok": index_result.get("ok"),
            "status": index_result.get("status"),
            "summary": index_result.get("summary"),
            "warnings": index_result.get("warnings", []),
            "errors": index_result.get("errors", []),
        },
    }


async def delete_upload(db: Database, config: AppConfig, upload_id: str) -> bool:
    row = await get_upload(db, upload_id)
    if row is None:
        return False
    upload_root = _upload_root_from_row(row)
    await db.execute("DELETE FROM uploads WHERE id = ?", (upload_id,))
    await asyncio.to_thread(shutil.rmtree, upload_root, True)
    return True


async def clear_uploads(db: Database, config: AppConfig) -> dict[str, Any]:
    rows = await db.fetchall("SELECT * FROM uploads WHERE promoted_at IS NULL")
    deleted = 0
    for row in rows:
        await db.execute("DELETE FROM uploads WHERE id = ?", (row["id"],))
        await asyncio.to_thread(shutil.rmtree, _upload_root_from_row(row), True)
        deleted += 1
    return {"deleted": deleted}


def _upload_root_from_row(row: dict[str, Any]) -> Path:
    return Path(row["storage_path"]).parents[1]


def _attachment_context_message(row: dict[str, Any], text: str) -> str:
    header = {
        "upload_id": row["upload_id"],
        "filename": row["original_filename"],
        "representation": row["representation"],
        "sha256": row["sha256"],
        "bytes": row["byte_count"],
    }
    return (
        "DELAMAIN upload attachment context.\n"
        f"Metadata: {json.dumps(header, sort_keys=True)}\n\n"
        f"{text}"
    )


def _native_attachment_content_parts(
    row: dict[str, Any],
    original_path: Path,
    fallback_text: str,
) -> list[dict[str, Any]]:
    header = {
        "upload_id": row["upload_id"],
        "filename": row["original_filename"],
        "representation": row["representation"],
        "sha256": row["sha256"],
        "bytes": row["byte_count"],
        "mime_type": row.get("mime_type"),
    }
    return [
        {
            "type": "text",
            "text": (
                "DELAMAIN upload attachment. Use the attached rich source file as the "
                "primary document. If this model route cannot inspect native files, use "
                "the fallback extracted text in the file part metadata.\n"
                f"Metadata: {json.dumps(header, sort_keys=True)}"
            ),
        },
        {
            "type": "delamain_upload_file",
            "file": {
                "filename": row["original_filename"],
                "path": str(original_path),
                "mime_type": row.get("mime_type") or "application/octet-stream",
                "sha256": row["sha256"],
                "byte_count": int(row["byte_count"]),
                "fallback_text": fallback_text,
            },
        },
    ]


def _runtime_paths(config: AppConfig) -> RuntimePaths:
    workspace = config.paths.llm_workspace
    return RuntimePaths(
        workspace_root=workspace,
        vault_root=config.paths.vault,
        syllabi_root=workspace / "syllabi",
        reference_root=workspace / "reference",
        transfer_root=workspace / "transfer",
        vault_index_root=workspace / "vault-index",
        skeleton_root=workspace / "skeleton_ref",
    )


def _non_colliding_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    for index in range(2, 10_000):
        candidate = path.with_name(f"{stem}-{index}{suffix}")
        if not candidate.exists():
            return candidate
    raise UploadError("Unable to choose promotion destination")


def _file_mtime_iso(path: Path) -> str:
    from datetime import datetime, timezone

    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()
