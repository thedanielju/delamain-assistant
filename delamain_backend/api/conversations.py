from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, status

from delamain_backend.agent.runner import new_id
from delamain_backend.api.deps import get_bus, get_config, get_db, get_run_manager
from delamain_backend.config import AppConfig
from delamain_backend.db import Database
from delamain_backend.events import EventBus
from delamain_backend.schemas import ConversationCreate, ConversationUpdate, PromptSubmit
from delamain_backend.settings_store import allowed_model_routes
from delamain_backend.uploads import UploadError, attachment_records_for_prompt

router = APIRouter(tags=["conversations"])


@router.get("/conversations")
async def list_conversations(db: Database = Depends(get_db)):
    rows = await db.fetchall(
        "SELECT * FROM conversations WHERE archived = 0 ORDER BY updated_at DESC"
    )
    return [_conversation_out(row) for row in rows]


@router.post("/conversations", status_code=status.HTTP_201_CREATED)
async def create_conversation(
    payload: ConversationCreate,
    config: AppConfig = Depends(get_config),
    db: Database = Depends(get_db),
):
    conversation_id = new_id("conv")
    model_route = payload.model_route
    if model_route is not None and model_route not in allowed_model_routes(config):
        raise HTTPException(status_code=400, detail="Unsupported model_route")
    if payload.folder_id is not None:
        await _require_folder(db, payload.folder_id)
    await db.execute(
        """
        INSERT INTO conversations(
            id, title, context_mode, model_route, incognito_route, sensitive_unlocked,
            folder_id
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            conversation_id,
            payload.title,
            payload.context_mode,
            model_route,
            1 if payload.incognito_route else 0,
            0,
            payload.folder_id,
        ),
    )
    row = await db.fetchone("SELECT * FROM conversations WHERE id = ?", (conversation_id,))
    return _conversation_out(row, default_model=config.models.default)


@router.get("/conversations/{conversation_id}")
async def get_conversation(conversation_id: str, db: Database = Depends(get_db)):
    row = await db.fetchone("SELECT * FROM conversations WHERE id = ?", (conversation_id,))
    if row is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return _conversation_out(row)


@router.patch("/conversations/{conversation_id}")
async def update_conversation(
    conversation_id: str,
    payload: ConversationUpdate,
    config: AppConfig = Depends(get_config),
    db: Database = Depends(get_db),
):
    row = await db.fetchone("SELECT * FROM conversations WHERE id = ?", (conversation_id,))
    if row is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    title = payload.title if payload.title is not None else row["title"]
    archived = row["archived"] if payload.archived is None else (1 if payload.archived else 0)
    payload_fields = (
        payload.model_fields_set if hasattr(payload, "model_fields_set") else payload.__fields_set__
    )
    folder_id = payload.folder_id if "folder_id" in payload_fields else row.get("folder_id")
    if folder_id is not None:
        await _require_folder(db, folder_id)
    model_route = payload.model_route if "model_route" in payload_fields else row["model_route"]
    if model_route is not None and model_route not in allowed_model_routes(config):
        raise HTTPException(status_code=400, detail="Unsupported model_route")
    incognito_route = row["incognito_route"]
    if "incognito_route" in payload_fields:
        incognito_route = 1 if payload.incognito_route else 0
    await db.execute(
        """
        UPDATE conversations
        SET title = ?,
            archived = ?,
            folder_id = ?,
            model_route = ?,
            incognito_route = ?,
            updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
        WHERE id = ?
        """,
        (title, archived, folder_id, model_route, incognito_route, conversation_id),
    )
    updated = await db.fetchone("SELECT * FROM conversations WHERE id = ?", (conversation_id,))
    return _conversation_out(updated)


@router.post("/conversations/{conversation_id}/sensitive/unlock")
async def unlock_sensitive(
    conversation_id: str,
    db: Database = Depends(get_db),
    bus: EventBus = Depends(get_bus),
):
    await _require_conversation(db, conversation_id)
    await db.execute(
        """
        UPDATE conversations
        SET sensitive_unlocked = 1,
            updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
        WHERE id = ?
        """,
        (conversation_id,),
    )
    await bus.emit(
        conversation_id=conversation_id,
        run_id=None,
        event_type="audit",
        payload={
            "action": "sensitive.unlocked",
            "summary": "Sensitive vault unlocked for this conversation",
            "sensitive_unlocked": True,
        },
    )
    row = await _require_conversation(db, conversation_id)
    return _conversation_out(row)


@router.post("/conversations/{conversation_id}/sensitive/lock")
async def lock_sensitive(
    conversation_id: str,
    db: Database = Depends(get_db),
    bus: EventBus = Depends(get_bus),
):
    await _require_conversation(db, conversation_id)
    await db.execute(
        """
        UPDATE conversations
        SET sensitive_unlocked = 0,
            updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
        WHERE id = ?
        """,
        (conversation_id,),
    )
    await bus.emit(
        conversation_id=conversation_id,
        run_id=None,
        event_type="audit",
        payload={
            "action": "sensitive.locked",
            "summary": "Sensitive vault locked for this conversation",
            "sensitive_unlocked": False,
        },
    )
    row = await _require_conversation(db, conversation_id)
    return _conversation_out(row)


@router.delete("/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(conversation_id: str, db: Database = Depends(get_db)):
    await db.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
    return None


@router.get("/conversations/{conversation_id}/messages")
async def list_messages(conversation_id: str, db: Database = Depends(get_db)):
    await _require_conversation(db, conversation_id)
    rows = await db.fetchall(
        "SELECT * FROM messages WHERE conversation_id = ? ORDER BY created_at ASC",
        (conversation_id,),
    )
    return rows


@router.post("/conversations/{conversation_id}/messages", status_code=status.HTTP_202_ACCEPTED)
async def submit_prompt(
    conversation_id: str,
    payload: PromptSubmit,
    config: AppConfig = Depends(get_config),
    db: Database = Depends(get_db),
    run_manager=Depends(get_run_manager),
):
    conversation = await _require_conversation(db, conversation_id)
    message_id = new_id("msg")
    run_id = new_id("run")
    context_mode = payload.context_mode or conversation["context_mode"]
    model_default = await _model_default(db, config)
    model_route = payload.model_route or conversation["model_route"] or model_default
    incognito_route = (
        payload.incognito_route
        if payload.incognito_route is not None
        else bool(conversation["incognito_route"])
    )
    generated_title = None
    if await _should_generate_title(db, conversation):
        generated_title = _title_from_prompt(payload.content)
        if generated_title == "New conversation":
            generated_title = None
    try:
        upload_attachments = await attachment_records_for_prompt(
            db,
            config,
            payload.attachments or [],
        )
    except UploadError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    statements = [
        (
            """
            INSERT INTO messages(id, conversation_id, role, content, status)
            VALUES (?, ?, 'user', ?, 'completed')
            """,
            (message_id, conversation_id, payload.content),
        ),
        (
            """
            INSERT INTO runs(
                id, conversation_id, user_message_id, status,
                context_mode, model_route, incognito_route
            )
            VALUES (?, ?, ?, 'queued', ?, ?, ?)
            """,
            (
                run_id,
                conversation_id,
                message_id,
                context_mode,
                model_route,
                1 if incognito_route else 0,
            ),
        ),
        (
            "UPDATE messages SET run_id = ? WHERE id = ?",
            (run_id, message_id),
        ),
        (
            """
            UPDATE conversations
            SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            WHERE id = ?
            """,
            (conversation_id,),
        ),
    ]
    if generated_title:
        statements.append(
            (
                """
                UPDATE conversations
                SET title = ?,
                    updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                WHERE id = ?
                """,
                (generated_title, conversation_id),
            )
        )
    selected_context_paths = [
        str(path).strip()
        for path in (payload.selected_context_paths or [])
        if str(path).strip()
    ]
    for path in selected_context_paths[:12]:
        statements.append(
            (
                """
                INSERT INTO pending_run_context(id, run_id, path, mode, reason)
                VALUES (?, ?, ?, 'vault_context_tray', 'Selected in composer tray')
                """,
                (new_id("prctx"), run_id, path),
            )
        )
    for attachment in upload_attachments:
        statements.append(
            (
                """
                INSERT INTO run_upload_attachments(
                    id, run_id, upload_id, original_filename, representation, included,
                    byte_count, sha256, content_path, content_sha256, context_char_count
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    new_id("rupl"),
                    run_id,
                    attachment["upload_id"],
                    attachment["original_filename"],
                    attachment["representation"],
                    1 if attachment["included"] else 0,
                    attachment["byte_count"],
                    attachment["sha256"],
                    attachment["content_path"],
                    attachment["content_sha256"],
                    attachment["context_char_count"],
                ),
            )
        )
    await db.execute_transaction(statements)
    if generated_title:
        await run_manager.bus.emit(
            conversation_id=conversation_id,
            run_id=run_id,
            event_type="conversation.title",
            payload={"conversation_id": conversation_id, "title": generated_title},
        )
    position_row = await db.fetchone(
        """
        SELECT COUNT(*) AS count
        FROM runs
        WHERE conversation_id = ?
          AND status IN ('queued', 'running', 'waiting_approval')
          AND created_at <= (SELECT created_at FROM runs WHERE id = ?)
        """,
        (conversation_id, run_id),
    )
    await run_manager.bus.emit(
        conversation_id=conversation_id,
        run_id=run_id,
        event_type="run.queued",
        payload={"run_id": run_id, "position": int(position_row["count"] or 1)},
    )
    run_manager.enqueue(run_id)
    return {"message_id": message_id, "run_id": run_id, "status": "queued"}


@router.get("/conversations/{conversation_id}/runs")
async def list_conversation_runs(conversation_id: str, db: Database = Depends(get_db)):
    await _require_conversation(db, conversation_id)
    rows = await db.fetchall(
        "SELECT * FROM runs WHERE conversation_id = ? ORDER BY created_at DESC",
        (conversation_id,),
    )
    return [_run_out(row) for row in rows]


async def _require_conversation(db: Database, conversation_id: str) -> dict:
    row = await db.fetchone("SELECT * FROM conversations WHERE id = ?", (conversation_id,))
    if row is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return row


async def _require_folder(db: Database, folder_id: str) -> dict:
    row = await db.fetchone("SELECT * FROM folders WHERE id = ?", (folder_id,))
    if row is None:
        raise HTTPException(status_code=404, detail="Folder not found")
    return row


def _conversation_out(row: dict, default_model: str | None = None) -> dict:
    return {
        **row,
        "incognito_route": bool(row["incognito_route"]),
        "sensitive_unlocked": bool(row["sensitive_unlocked"]),
        "archived": bool(row["archived"]),
        "model_route": row["model_route"] or default_model,
    }


async def _should_generate_title(db: Database, conversation: dict) -> bool:
    title = (conversation.get("title") or "").strip()
    if title and title.lower() not in {"untitled", "new conversation"}:
        return False
    row = await db.fetchone(
        "SELECT value FROM settings WHERE key = 'title_generation_enabled'"
    )
    if row is None:
        return True
    try:
        return bool(json.loads(row["value"]))
    except json.JSONDecodeError:
        return True


async def _model_default(db: Database, config: AppConfig) -> str:
    row = await db.fetchone("SELECT value FROM settings WHERE key = 'model_default'")
    if row is None:
        return config.models.default
    try:
        value = json.loads(row["value"])
    except json.JSONDecodeError:
        return config.models.default
    return value if isinstance(value, str) else config.models.default


def _title_from_prompt(content: str) -> str:
    words = []
    for raw in content.replace("\n", " ").split():
        word = raw.strip(" \t\r\n`*_[](){}<>#|")
        if word:
            words.append(word)
        if len(words) >= 8:
            break
    title = " ".join(words).strip()
    if not title:
        return "New conversation"
    if len(title) > 72:
        title = title[:69].rstrip() + "..."
    return title


def _run_out(row: dict) -> dict:
    return {**row, "incognito_route": bool(row["incognito_route"])}
