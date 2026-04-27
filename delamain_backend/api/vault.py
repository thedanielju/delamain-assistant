from __future__ import annotations

import asyncio
import difflib
import hashlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from delamain_backend.agent.context import load_context_for_run
from delamain_backend.agent.runner import new_id
from delamain_backend.api.audit import audit_event
from delamain_backend.api.deps import get_bus, get_config, get_db, get_run_manager
from delamain_backend.agent import RunManager
from delamain_backend.config import AppConfig
from delamain_backend.db import Database
from delamain_backend.errors import SensitiveLocked, ToolPolicyDenied
from delamain_backend.events import EventBus
from delamain_backend.security.paths import PathPolicy
from delamain_backend.schemas import (
    VaultContextPinRequest,
    VaultContextPreviewRequest,
    VaultEnrichmentBatchRequest,
    VaultEnrichmentRunRequest,
    VaultFolderInitRequest,
    VaultMaintenanceProposalCreate,
    VaultMaintenanceProposalUpdate,
    VaultPolicyExclusionCreate,
    VaultRelationFeedbackRequest,
)
from delamain_backend.security.vault import (
    graph_metadata_node_for_path,
    load_vault_graph,
    preview_context_candidates,
    policy_exclusions,
    read_vault_note,
    resolve_vault_relative_path,
    vault_metadata_path_allowed,
    vault_graph_neighborhood,
    vault_graph_shortest_path,
)
from delamain_backend.vault_enrichment import enrichment_status, run_enrichment
from delamain_backend.vault_generated import (
    generated_relation_candidates,
    load_generated_metadata,
    set_generated_relation_feedback,
    write_generated_metadata,
)
from delamain_backend.vault_staleness import vault_sync_conflict_paths

router = APIRouter(tags=["vault"])


@router.get("/vault/graph")
async def get_vault_graph(
    folder: str | None = None,
    tag: str | None = None,
    limit: int = Query(2000, ge=1, le=5000),
    config: AppConfig = Depends(get_config),
):
    graph = load_vault_graph(config, folder=folder, tag=tag, limit=limit)
    graph.pop("known_paths", None)
    return graph


@router.get("/vault/graph/neighborhood")
async def get_vault_graph_neighborhood(
    path: str,
    hops: int = Query(1, ge=1, le=4),
    limit: int = Query(80, ge=1, le=500),
    config: AppConfig = Depends(get_config),
):
    try:
        return vault_graph_neighborhood(config, path, hops=hops, limit=limit)
    except SensitiveLocked as exc:
        raise HTTPException(status_code=423, detail=str(exc)) from exc
    except ToolPolicyDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/vault/graph/path")
async def get_vault_graph_path(
    from_path: str = Query(alias="from"),
    to_path: str = Query(alias="to"),
    config: AppConfig = Depends(get_config),
):
    try:
        return vault_graph_shortest_path(config, from_path, to_path)
    except SensitiveLocked as exc:
        raise HTTPException(status_code=423, detail=str(exc)) from exc
    except ToolPolicyDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/vault/note")
async def get_vault_note(
    path: str,
    conversation_id: str | None = None,
    config: AppConfig = Depends(get_config),
    db: Database = Depends(get_db),
):
    sensitive_unlocked = False
    if conversation_id is not None:
        conversation = await _require_conversation(db, conversation_id)
        sensitive_unlocked = bool(conversation["sensitive_unlocked"])
    try:
        note = read_vault_note(config, path, sensitive_unlocked=sensitive_unlocked)
    except SensitiveLocked as exc:
        raise HTTPException(status_code=423, detail=str(exc)) from exc
    except ToolPolicyDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=404, detail="Vault note not found") from exc
    return {
        "path": note.relative_path,
        "title": note.title,
        "content": note.content,
        "bytes": note.byte_count,
        "sha256": note.sha256,
        "tags": note.tags,
        "backlinks": note.backlinks,
        "truncated": note.truncated,
        "source_type": note.source_type,
    }


@router.get("/vault/policy/exclusions")
async def get_vault_policy_exclusions(
    conversation_id: str | None = None,
    config: AppConfig = Depends(get_config),
    db: Database = Depends(get_db),
):
    sensitive_unlocked = False
    if conversation_id is not None:
        conversation = await _require_conversation(db, conversation_id)
        sensitive_unlocked = bool(conversation["sensitive_unlocked"])
    return policy_exclusions(
        config,
        conversation_sensitive_unlocked=sensitive_unlocked,
    )


@router.post("/vault/policy/exclusions")
async def add_vault_policy_exclusion(
    payload: VaultPolicyExclusionCreate,
    config: AppConfig = Depends(get_config),
    db: Database = Depends(get_db),
    bus: EventBus = Depends(get_bus),
):
    vault_policy = config.paths.vault / "vault_policy.md"
    if not vault_policy.exists():
        raise HTTPException(status_code=404, detail="Root vault_policy.md not found")
    content = vault_policy.read_text(encoding="utf-8")
    line = f"- `{payload.pattern}`"
    if payload.reason:
        line += f" # {payload.reason}"
    if payload.pattern not in content:
        marker = "## Ignore Globs"
        if marker in content:
            content = content.replace(marker, f"{marker}\n\n{line}", 1)
        else:
            content = content.rstrip() + f"\n\n## Ignore Globs\n\n{line}\n"
        vault_policy.write_text(content, encoding="utf-8")
    await audit_event(
        db=db,
        bus=bus,
        conversation_id=None,
        action="vault_policy.exclusion_added",
        summary="Vault policy exclusion added",
        payload={"pattern": payload.pattern, "reason": payload.reason},
    )
    return {"pattern": payload.pattern, "path": str(vault_policy)}


@router.delete("/vault/policy/exclusions")
async def delete_vault_policy_exclusion(
    path: str,
    config: AppConfig = Depends(get_config),
    db: Database = Depends(get_db),
    bus: EventBus = Depends(get_bus),
):
    vault_policy = config.paths.vault / "vault_policy.md"
    if not vault_policy.exists():
        raise HTTPException(status_code=404, detail="Root vault_policy.md not found")
    content = vault_policy.read_text(encoding="utf-8")
    lines = content.splitlines()
    next_lines = [line for line in lines if path not in line]
    if len(next_lines) != len(lines):
        vault_policy.write_text("\n".join(next_lines).rstrip() + "\n", encoding="utf-8")
    await audit_event(
        db=db,
        bus=bus,
        conversation_id=None,
        action="vault_policy.exclusion_removed",
        summary="Vault policy exclusion removed",
        payload={"path": path},
    )
    return {"path": path, "policy_path": str(vault_policy)}


@router.post("/vault/context/preview")
@router.post("/vault/context-capsules")
async def preview_vault_context(
    payload: VaultContextPreviewRequest,
    config: AppConfig = Depends(get_config),
):
    return {
        "items": preview_context_candidates(config, payload.prompt, limit=8),
        "source": "vault-index",
    }


@router.get("/vault/enrichment/status")
async def get_vault_enrichment_status(config: AppConfig = Depends(get_config)):
    return await enrichment_status(config)


@router.post("/vault/enrichment/run")
async def run_vault_enrichment(
    payload: VaultEnrichmentRunRequest,
    config: AppConfig = Depends(get_config),
    db: Database = Depends(get_db),
    bus: EventBus = Depends(get_bus),
    run_manager: RunManager = Depends(get_run_manager),
):
    result = await run_enrichment(
        config=config,
        db=db,
        model_client=run_manager.model_client,
        paths=payload.paths,
        limit=payload.limit,
        force=payload.force,
        create_proposals=payload.create_proposals,
    )
    await audit_event(
        db=db,
        bus=bus,
        conversation_id=None,
        action="vault_enrichment.run",
        summary="Vault AI enrichment run completed",
        payload={
            "processed": len(result["processed"]),
            "skipped": len(result["skipped"]),
            "errors": len(result["errors"]),
            "proposals_created": result["proposals_created"],
        },
    )
    return result


@router.get("/vault/enrichment/batch")
async def get_vault_enrichment_batch_status(request: Request):
    return getattr(
        request.app.state,
        "vault_enrichment_batch_status",
        {
            "status": "idle",
            "running": False,
            "started_at": None,
            "finished_at": None,
            "result": None,
            "error": None,
        },
    )


@router.post("/vault/enrichment/batch", status_code=status.HTTP_202_ACCEPTED)
async def start_vault_enrichment_batch(
    payload: VaultEnrichmentBatchRequest,
    request: Request,
    config: AppConfig = Depends(get_config),
    db: Database = Depends(get_db),
    bus: EventBus = Depends(get_bus),
    run_manager: RunManager = Depends(get_run_manager),
):
    current_task = getattr(request.app.state, "vault_enrichment_batch_task", None)
    if current_task is not None and not current_task.done():
        raise HTTPException(status_code=409, detail="Vault enrichment batch is already running")
    status_payload = {
        "status": "queued",
        "running": True,
        "started_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "finished_at": None,
        "request": payload.model_dump() if hasattr(payload, "model_dump") else payload.dict(),
        "result": None,
        "error": None,
    }
    request.app.state.vault_enrichment_batch_status = status_payload
    request.app.state.vault_enrichment_batch_task = asyncio.create_task(
        _run_vault_enrichment_batch(
            request=request,
            config=config,
            db=db,
            bus=bus,
            run_manager=run_manager,
            payload=payload,
        )
    )
    return status_payload


@router.get("/vault/enrichment/relations")
async def list_vault_generated_relations(config: AppConfig = Depends(get_config)):
    metadata = load_generated_metadata(config)
    return {"relations": generated_relation_candidates(metadata)}


@router.post("/vault/enrichment/relations/feedback")
async def set_vault_generated_relation_feedback(
    payload: VaultRelationFeedbackRequest,
    config: AppConfig = Depends(get_config),
    db: Database = Depends(get_db),
    bus: EventBus = Depends(get_bus),
):
    metadata = load_generated_metadata(config)
    feedback = set_generated_relation_feedback(
        metadata,
        from_path=payload.from_path,
        to_path=payload.to_path,
        relation_type=payload.relation_type,
        decision=payload.decision,
    )
    write_generated_metadata(config, metadata)
    await audit_event(
        db=db,
        bus=bus,
        conversation_id=None,
        action="vault_enrichment.relation_feedback",
        summary=f"Generated vault relation {payload.decision}",
        payload=feedback,
    )
    return {"feedback": feedback, "relations": generated_relation_candidates(metadata)}


async def _run_vault_enrichment_batch(
    *,
    request: Request,
    config: AppConfig,
    db: Database,
    bus: EventBus,
    run_manager: RunManager,
    payload: VaultEnrichmentBatchRequest,
) -> None:
    request.app.state.vault_enrichment_batch_status = {
        **request.app.state.vault_enrichment_batch_status,
        "status": "running",
        "running": True,
    }
    try:
        result = await run_enrichment(
            config=config,
            db=db,
            model_client=run_manager.model_client,
            paths=None,
            limit=payload.limit,
            force=payload.force,
            create_proposals=payload.create_proposals,
        )
        request.app.state.vault_enrichment_batch_status = {
            **request.app.state.vault_enrichment_batch_status,
            "status": "completed" if result.get("ok") else "completed_with_errors",
            "running": False,
            "finished_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "result": result,
            "error": None,
        }
        await audit_event(
            db=db,
            bus=bus,
            conversation_id=None,
            action="vault_enrichment.batch_completed",
            summary="Vault enrichment batch completed",
            payload={
                "processed": len(result.get("processed", [])),
                "skipped": len(result.get("skipped", [])),
                "errors": len(result.get("errors", [])),
            },
        )
    except Exception as exc:
        request.app.state.vault_enrichment_batch_status = {
            **request.app.state.vault_enrichment_batch_status,
            "status": "failed",
            "running": False,
            "finished_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "result": None,
            "error": f"{type(exc).__name__}: {exc}",
        }


@router.post("/vault/folders/init")
async def init_vault_structured_folder(
    payload: VaultFolderInitRequest,
    config: AppConfig = Depends(get_config),
    db: Database = Depends(get_db),
    bus: EventBus = Depends(get_bus),
):
    helper = config.paths.llm_workspace / "bin" / "delamain-vault-index"
    if not helper.exists():
        raise HTTPException(status_code=503, detail="delamain-vault-index helper not found")
    try:
        process = await asyncio.create_subprocess_exec(
            str(helper),
            "init-folder",
            "--kind",
            payload.kind,
            "--name",
            payload.name,
            "--json",
            cwd=str(config.paths.llm_workspace),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=60)
    except asyncio.TimeoutError as exc:
        raise HTTPException(status_code=504, detail="Structured folder initialization timed out") from exc
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Structured folder initialization failed: {exc}") from exc

    result = _decode_helper_json(stdout)
    if process.returncode != 0 or not result.get("ok", False):
        detail = result.get("error") or stderr.decode("utf-8", errors="replace")[:1000]
        raise HTTPException(
            status_code=500,
            detail=detail or "Structured folder initialization failed",
        )
    await audit_event(
        db=db,
        bus=bus,
        conversation_id=None,
        action="vault_folder.initialized",
        summary=f"Initialized {payload.kind} structured folder",
        payload={"kind": payload.kind, "name": payload.name, "result": result},
    )
    return result


@router.get("/conversations/{conversation_id}/context/pins")
async def list_context_pins(
    conversation_id: str,
    config: AppConfig = Depends(get_config),
    db: Database = Depends(get_db),
):
    return await _context_pins_payload(config, db, conversation_id)


async def _context_pins_payload(
    config: AppConfig,
    db: Database,
    conversation_id: str,
) -> dict[str, Any]:
    conversation = await _require_conversation(db, conversation_id)
    sensitive_unlocked = bool(conversation["sensitive_unlocked"])
    rows = await db.fetchall(
        """
        SELECT path, title, mode, created_at, updated_at
        FROM context_pins
        WHERE conversation_id = ?
        ORDER BY created_at ASC
        """,
        (conversation_id,),
    )
    items: list[dict[str, Any]] = []
    for row in rows:
        node = graph_metadata_node_for_path(
            config,
            str(row["path"]),
            sensitive_unlocked=sensitive_unlocked,
        )
        if node is None:
            continue
        path = str(node.get("path") or row["path"])
        title = str(node.get("title") or row["title"] or path)
        items.append(
            {
                "path": path,
                "title": title,
                "mode": row["mode"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
        )
    return {"paths": [item["path"] for item in items], "items": items}


@router.post("/conversations/{conversation_id}/context/pin")
@router.post("/conversations/{conversation_id}/context/pins")
async def pin_context(
    conversation_id: str,
    payload: VaultContextPinRequest,
    config: AppConfig = Depends(get_config),
    db: Database = Depends(get_db),
    bus: EventBus = Depends(get_bus),
):
    conversation = await _require_conversation(db, conversation_id)
    sensitive_unlocked = bool(conversation["sensitive_unlocked"])
    pinned: list[dict[str, Any]] = []
    try:
        for raw_path in payload.paths:
            note = read_vault_note(
                config,
                raw_path,
                sensitive_unlocked=sensitive_unlocked,
                max_bytes=1,
            )
            await db.execute(
                """
                INSERT INTO context_pins(id, conversation_id, path, title, mode)
                VALUES (?, ?, ?, ?, 'vault_note_pin')
                ON CONFLICT(conversation_id, path) DO UPDATE SET
                    title = excluded.title,
                    updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                """,
                (new_id("pin"), conversation_id, note.relative_path, note.title),
            )
            pinned.append(
                {"path": note.relative_path, "title": note.title, "mode": "vault_note_pin"}
            )
    except SensitiveLocked as exc:
        raise HTTPException(status_code=423, detail=str(exc)) from exc
    except ToolPolicyDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=404, detail="Vault note not found") from exc
    await audit_event(
        db=db,
        bus=bus,
        conversation_id=conversation_id,
        action="context.pin_added",
        summary=f"Pinned {len(pinned)} vault note(s) to conversation context",
        payload={"paths": [item["path"] for item in pinned]},
    )
    return await _context_pins_payload(config, db, conversation_id)


@router.delete("/conversations/{conversation_id}/context/pin")
@router.delete("/conversations/{conversation_id}/context/pins")
async def unpin_context(
    conversation_id: str,
    path: str,
    config: AppConfig = Depends(get_config),
    db: Database = Depends(get_db),
    bus: EventBus = Depends(get_bus),
):
    await _require_conversation(db, conversation_id)
    try:
        relative_path = resolve_vault_relative_path(
            config,
            path,
            sensitive_unlocked=True,
            must_exist=False,
        )
    except ToolPolicyDenied:
        relative_path = path
    await db.execute(
        "DELETE FROM context_pins WHERE conversation_id = ? AND path = ?",
        (conversation_id, relative_path),
    )
    await audit_event(
        db=db,
        bus=bus,
        conversation_id=conversation_id,
        action="context.pin_removed",
        summary="Removed vault note from conversation context pins",
        payload={"path": relative_path},
    )
    return await _context_pins_payload(config, db, conversation_id)


@router.post("/conversations/{conversation_id}/context/preview")
async def preview_context(
    conversation_id: str,
    payload: VaultContextPreviewRequest,
    config: AppConfig = Depends(get_config),
    db: Database = Depends(get_db),
):
    conversation = await _require_conversation(db, conversation_id)
    paths = payload.paths
    if paths is None:
        candidates = preview_context_candidates(
            config,
            payload.prompt,
            sensitive_unlocked=bool(conversation["sensitive_unlocked"]),
        )
        paths = [str(item["path"]) for item in candidates]
        if not paths:
            pins = await _context_pins_payload(config, db, conversation_id)
            paths = [str(path) for path in pins["paths"]]
    loaded = load_context_for_run(
        config,
        payload.context_mode or conversation["context_mode"],
        selected_context_paths=paths,
        sensitive_unlocked=bool(conversation["sensitive_unlocked"]),
    )
    return {
        "context_mode": payload.context_mode or conversation["context_mode"],
        "items": loaded.items,
        "prompt_message_count": len(loaded.prompt_messages),
    }


@router.get("/vault/maintenance/proposals")
async def list_maintenance_proposals(
    status_filter: str | None = Query(default=None, alias="status"),
    config: AppConfig = Depends(get_config),
    db: Database = Depends(get_db),
):
    if status_filter:
        rows = await db.fetchall(
            """
            SELECT * FROM vault_maintenance_proposals
            WHERE status = ?
            ORDER BY created_at DESC
            """,
            (status_filter,),
        )
    else:
        rows = await db.fetchall(
            "SELECT * FROM vault_maintenance_proposals ORDER BY created_at DESC"
        )
    return [
        proposal
        for row in rows
        if (proposal := _maintenance_proposal_out(row, config=config)) is not None
    ]


@router.post("/vault/maintenance/proposals", status_code=status.HTTP_201_CREATED)
async def create_maintenance_proposal(
    payload: VaultMaintenanceProposalCreate,
    config: AppConfig = Depends(get_config),
    db: Database = Depends(get_db),
):
    if payload.conversation_id is not None:
        await _require_conversation(db, payload.conversation_id)
    proposal_id = new_id("vmp")
    await db.execute(
        """
        INSERT INTO vault_maintenance_proposals(
            id, conversation_id, kind, title, description, paths_json, payload_json, status
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, 'proposed')
        """,
        (
            proposal_id,
            payload.conversation_id,
            payload.kind,
            payload.title,
            payload.description,
            json.dumps(payload.paths, sort_keys=True),
            json.dumps(payload.payload, sort_keys=True),
        ),
    )
    row = await db.fetchone("SELECT * FROM vault_maintenance_proposals WHERE id = ?", (proposal_id,))
    return _maintenance_proposal_out(row, config=config) or _maintenance_proposal_out(row)


@router.patch("/vault/maintenance/proposals/{proposal_id}")
async def update_maintenance_proposal(
    proposal_id: str,
    payload: VaultMaintenanceProposalUpdate,
    db: Database = Depends(get_db),
):
    row = await db.fetchone(
        "SELECT * FROM vault_maintenance_proposals WHERE id = ?",
        (proposal_id,),
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Maintenance proposal not found")
    status_value = payload.status or row["status"]
    if status_value not in {"proposed", "accepted", "rejected", "applied", "superseded", "reverted"}:
        raise HTTPException(status_code=400, detail="Invalid proposal status")
    title = payload.title if payload.title is not None else row["title"]
    description = payload.description if payload.description is not None else row["description"]
    paths = json.loads(row["paths_json"])
    if payload.paths is not None:
        paths = payload.paths
    proposal_payload = json.loads(row["payload_json"])
    if payload.payload is not None:
        proposal_payload = payload.payload
    resolved_sql = (
        ", resolved_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')"
        if status_value in {"accepted", "rejected", "applied", "superseded", "reverted"}
        else ""
    )
    await db.execute(
        f"""
        UPDATE vault_maintenance_proposals
        SET status = ?,
            title = ?,
            description = ?,
            paths_json = ?,
            payload_json = ?,
            updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            {resolved_sql}
        WHERE id = ?
        """,
        (
            status_value,
            title,
            description,
            json.dumps(paths, sort_keys=True),
            json.dumps(proposal_payload, sort_keys=True),
            proposal_id,
        ),
    )
    updated = await db.fetchone(
        "SELECT * FROM vault_maintenance_proposals WHERE id = ?",
        (proposal_id,),
    )
    return _maintenance_proposal_out(updated)


@router.get("/vault/maintenance/proposals/{proposal_id}/diff")
async def preview_maintenance_proposal_diff(
    proposal_id: str,
    config: AppConfig = Depends(get_config),
    db: Database = Depends(get_db),
):
    row = await _require_maintenance_proposal(db, proposal_id)
    proposal = _maintenance_proposal_out(row)
    try:
        preview = _preview_exact_replace_plan(config, proposal)
    except (SensitiveLocked, ToolPolicyDenied) as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"proposal": proposal, **preview}


@router.post("/vault/maintenance/proposals/{proposal_id}/apply")
async def apply_maintenance_proposal(
    proposal_id: str,
    config: AppConfig = Depends(get_config),
    db: Database = Depends(get_db),
    bus: EventBus = Depends(get_bus),
):
    row = await _require_maintenance_proposal(db, proposal_id)
    proposal = _maintenance_proposal_out(row)
    apply_result: dict[str, Any] = {"mode": "status_only"}
    next_payload = proposal["payload"]
    try:
        if _proposal_action(next_payload) in {"exact_replace", "replace_text", "patch_text_file"}:
            apply_result = _apply_exact_replace_plan(config, proposal, db)
            next_payload = {
                **next_payload,
                "applied": apply_result,
            }
    except (SensitiveLocked, ToolPolicyDenied) as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await db.execute(
        """
        UPDATE vault_maintenance_proposals
        SET status = 'applied',
            payload_json = ?,
            updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
            resolved_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
        WHERE id = ?
        """,
        (json.dumps(next_payload, sort_keys=True), proposal_id),
    )
    updated = await db.fetchone(
        "SELECT * FROM vault_maintenance_proposals WHERE id = ?",
        (proposal_id,),
    )
    await audit_event(
        db=db,
        bus=bus,
        conversation_id=row.get("conversation_id"),
        action="vault_maintenance.proposal_applied",
        summary=f"Applied vault maintenance proposal: {row['title']}",
        payload={"proposal_id": proposal_id, "kind": row["kind"], "result": apply_result},
    )
    return _maintenance_proposal_out(updated)


@router.post("/vault/maintenance/proposals/{proposal_id}/reject")
async def reject_maintenance_proposal(
    proposal_id: str,
    db: Database = Depends(get_db),
    bus: EventBus = Depends(get_bus),
):
    row = await _require_maintenance_proposal(db, proposal_id)
    await db.execute(
        """
        UPDATE vault_maintenance_proposals
        SET status = 'rejected',
            updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
            resolved_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
        WHERE id = ?
        """,
        (proposal_id,),
    )
    updated = await db.fetchone(
        "SELECT * FROM vault_maintenance_proposals WHERE id = ?",
        (proposal_id,),
    )
    await audit_event(
        db=db,
        bus=bus,
        conversation_id=row.get("conversation_id"),
        action="vault_maintenance.proposal_rejected",
        summary=f"Rejected vault maintenance proposal: {row['title']}",
        payload={"proposal_id": proposal_id, "kind": row["kind"]},
    )
    return _maintenance_proposal_out(updated)


@router.post("/vault/maintenance/proposals/{proposal_id}/revert")
async def revert_maintenance_proposal(
    proposal_id: str,
    config: AppConfig = Depends(get_config),
    db: Database = Depends(get_db),
    bus: EventBus = Depends(get_bus),
):
    row = await _require_maintenance_proposal(db, proposal_id)
    proposal = _maintenance_proposal_out(row)
    try:
        revert_result = _revert_exact_replace_plan(config, proposal, db)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    next_payload = {
        **proposal["payload"],
        "reverted": revert_result,
    }
    await db.execute(
        """
        UPDATE vault_maintenance_proposals
        SET status = 'reverted',
            payload_json = ?,
            updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
            resolved_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
        WHERE id = ?
        """,
        (json.dumps(next_payload, sort_keys=True), proposal_id),
    )
    updated = await db.fetchone(
        "SELECT * FROM vault_maintenance_proposals WHERE id = ?",
        (proposal_id,),
    )
    await audit_event(
        db=db,
        bus=bus,
        conversation_id=row.get("conversation_id"),
        action="vault_maintenance.proposal_reverted",
        summary=f"Reverted vault maintenance proposal: {row['title']}",
        payload={"proposal_id": proposal_id, "kind": row["kind"], "result": revert_result},
    )
    return _maintenance_proposal_out(updated)


async def _require_conversation(db: Database, conversation_id: str) -> dict[str, Any]:
    row = await db.fetchone("SELECT * FROM conversations WHERE id = ?", (conversation_id,))
    if row is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return row


async def _require_maintenance_proposal(db: Database, proposal_id: str) -> dict[str, Any]:
    row = await db.fetchone(
        "SELECT * FROM vault_maintenance_proposals WHERE id = ?",
        (proposal_id,),
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Maintenance proposal not found")
    return row


def _maintenance_proposal_out(
    row: dict[str, Any],
    *,
    config: AppConfig | None = None,
) -> dict[str, Any] | None:
    paths = json.loads(row["paths_json"])
    payload = json.loads(row["payload_json"])
    if config is not None and not _maintenance_proposal_metadata_allowed(config, paths, payload):
        return None
    return {
        **row,
        "paths": paths,
        "payload": payload,
    }


def _maintenance_proposal_metadata_allowed(
    config: AppConfig,
    paths: Any,
    payload: Any,
) -> bool:
    for path in _maintenance_proposal_paths(paths, payload):
        if not vault_metadata_path_allowed(config, path, sensitive_unlocked=False):
            return False
    return True


def _maintenance_proposal_paths(paths: Any, payload: Any) -> list[str]:
    collected: list[str] = []
    if isinstance(paths, list):
        collected.extend(str(path) for path in paths if str(path).strip())
    elif isinstance(paths, str) and paths.strip():
        collected.append(paths.strip())
    if isinstance(payload, dict):
        raw_path = payload.get("path")
        if isinstance(raw_path, str) and raw_path.strip():
            collected.append(raw_path.strip())
        raw_paths = payload.get("paths")
        if isinstance(raw_paths, list):
            collected.extend(str(path) for path in raw_paths if str(path).strip())
    return sorted(set(collected))


def _decode_helper_json(data: bytes) -> dict[str, Any]:
    try:
        parsed = json.loads(data.decode("utf-8"))
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _proposal_action(payload: dict[str, Any]) -> str | None:
    action = payload.get("action") or payload.get("action_type") or payload.get("command")
    return str(action) if isinstance(action, str) else None


def _proposal_changes(proposal: dict[str, Any]) -> list[dict[str, Any]]:
    payload = proposal["payload"]
    raw_changes = payload.get("changes")
    if isinstance(raw_changes, list):
        return [item for item in raw_changes if isinstance(item, dict)]
    return [
        {
            "path": payload.get("path") or (proposal["paths"][0] if proposal["paths"] else None),
            "old_text": payload.get("old_text"),
            "new_text": payload.get("new_text"),
            "expected_sha256": payload.get("expected_sha256"),
        }
    ]


def _preview_exact_replace_plan(config: AppConfig, proposal: dict[str, Any]) -> dict[str, Any]:
    payload = proposal["payload"]
    if _proposal_action(payload) not in {"exact_replace", "replace_text", "patch_text_file"}:
        return {
            "applicable": False,
            "reason": "Proposal has no supported exact replacement action",
            "action": _proposal_action(payload),
            "changes": [],
            "diff": "",
        }
    changes = _proposal_changes(proposal)
    if len(changes) != 1:
        return {
            "applicable": False,
            "reason": "V1 supports exactly one exact replacement per proposal",
            "action": "exact_replace",
            "changes": [],
            "diff": "",
        }
    previews: list[dict[str, Any]] = []
    diffs: list[str] = []
    for change in changes:
        preview = _preview_exact_replace_change(config, change)
        previews.append(preview)
        if preview["diff"]:
            diffs.append(preview["diff"])
    applicable = all(item["applicable"] for item in previews) and bool(previews)
    return {
        "applicable": applicable,
        "reason": None if applicable else "; ".join(
            item["reason"] for item in previews if item.get("reason")
        ) or "No applicable changes",
        "action": "exact_replace",
        "changes": previews,
        "diff": "\n".join(diffs),
    }


def _preview_exact_replace_change(config: AppConfig, change: dict[str, Any]) -> dict[str, Any]:
    raw_path = change.get("path")
    old_text = change.get("old_text")
    new_text = change.get("new_text")
    expected_sha256 = change.get("expected_sha256")
    if not isinstance(raw_path, str) or not raw_path.strip():
        return {"applicable": False, "reason": "Missing change path", "diff": ""}
    if not isinstance(old_text, str) or not isinstance(new_text, str):
        return {"path": raw_path, "applicable": False, "reason": "Missing old_text/new_text", "diff": ""}
    note = read_vault_note(
        config,
        raw_path,
        sensitive_unlocked=False,
        max_bytes=1,
    )
    if note.source_type != "vault_note":
        raise ToolPolicyDenied("Maintenance writes are limited to Obsidian vault notes in V1")
    if note.relative_path in vault_sync_conflict_paths(config):
        return {
            "path": note.relative_path,
            "applicable": False,
            "reason": "File has a Syncthing conflict; resolve sync state before applying maintenance writes",
            "diff": "",
        }
    PathPolicy(config).check(
        str(note.path),
        operation="write",
        sensitive_unlocked=False,
        allow_binary=False,
    )
    data = note.path.read_bytes()
    sha256 = hashlib.sha256(data).hexdigest()
    if isinstance(expected_sha256, str) and expected_sha256 and expected_sha256 != sha256:
        return {
            "path": note.relative_path,
            "applicable": False,
            "reason": "File sha256 did not match expected_sha256",
            "old_sha256": sha256,
            "diff": "",
        }
    original = data.decode("utf-8", errors="strict")
    occurrences = original.count(old_text)
    updated = original.replace(old_text, new_text, 1)
    diff = ""
    if occurrences == 1:
        diff = "".join(
            difflib.unified_diff(
                original.splitlines(keepends=True),
                updated.splitlines(keepends=True),
                fromfile=f"a/{note.relative_path}",
                tofile=f"b/{note.relative_path}",
            )
        )
    return {
        "path": note.relative_path,
        "applicable": occurrences == 1,
        "reason": None if occurrences == 1 else f"old_text must match exactly once; matched {occurrences} times",
        "occurrences": occurrences,
        "old_sha256": sha256,
        "new_sha256": hashlib.sha256(updated.encode("utf-8")).hexdigest() if occurrences == 1 else None,
        "old_byte_count": len(data),
        "new_byte_count": len(updated.encode("utf-8")) if occurrences == 1 else None,
        "diff": diff,
    }


def _apply_exact_replace_plan(
    config: AppConfig,
    proposal: dict[str, Any],
    db: Database,
) -> dict[str, Any]:
    preview = _preview_exact_replace_plan(config, proposal)
    if not preview["applicable"]:
        raise ValueError(preview["reason"] or "Proposal is not applicable")
    backup_dir = db.path.parent / "vault-maintenance-backups" / proposal["id"]
    backup_dir.mkdir(parents=True, exist_ok=True)
    applied_changes: list[dict[str, Any]] = []
    for change in _proposal_changes(proposal):
        note = read_vault_note(config, str(change["path"]), sensitive_unlocked=False, max_bytes=1)
        PathPolicy(config).check(
            str(note.path),
            operation="write",
            sensitive_unlocked=False,
            allow_binary=False,
        )
        original_bytes = note.path.read_bytes()
        original_sha = hashlib.sha256(original_bytes).hexdigest()
        original = original_bytes.decode("utf-8", errors="strict")
        old_text = str(change["old_text"])
        new_text = str(change["new_text"])
        if original.count(old_text) != 1:
            raise ValueError("old_text must match exactly once at apply time")
        backup_path = backup_dir / f"{note.path.name}.{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.{len(applied_changes)}.bak"
        shutil.copy2(note.path, backup_path)
        updated = original.replace(old_text, new_text, 1)
        note.path.write_text(updated, encoding="utf-8")
        new_bytes = updated.encode("utf-8")
        applied_changes.append(
            {
                "path": note.relative_path,
                "target_path": str(note.path),
                "backup_path": str(backup_path),
                "old_sha256": original_sha,
                "new_sha256": hashlib.sha256(new_bytes).hexdigest(),
                "old_byte_count": len(original_bytes),
                "new_byte_count": len(new_bytes),
            }
        )
    return {
        "mode": "exact_replace",
        "applied_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "changes": applied_changes,
    }


def _revert_exact_replace_plan(
    config: AppConfig,
    proposal: dict[str, Any],
    db: Database,
) -> dict[str, Any]:
    applied = proposal["payload"].get("applied")
    if not isinstance(applied, dict) or applied.get("mode") != "exact_replace":
        raise ValueError("Proposal has no exact replacement application to revert")
    raw_changes = applied.get("changes")
    if not isinstance(raw_changes, list) or not raw_changes:
        raise ValueError("Proposal has no applied changes to revert")
    backup_root = (db.path.parent / "vault-maintenance-backups").resolve()
    reverted: list[dict[str, Any]] = []
    for raw_change in raw_changes:
        if not isinstance(raw_change, dict):
            continue
        target = Path(str(raw_change.get("target_path") or "")).resolve()
        backup = Path(str(raw_change.get("backup_path") or "")).resolve()
        expected_sha = raw_change.get("new_sha256")
        PathPolicy(config).check(
            str(target),
            operation="write",
            sensitive_unlocked=False,
            allow_binary=False,
        )
        if not backup.is_relative_to(backup_root):
            raise ValueError("Backup path is outside DELAMAIN maintenance backups")
        if not target.is_file():
            raise FileNotFoundError(f"Applied target is missing: {target}")
        if not backup.is_file():
            raise FileNotFoundError(f"Applied backup is missing: {backup}")
        current_bytes = target.read_bytes()
        current_sha = hashlib.sha256(current_bytes).hexdigest()
        if isinstance(expected_sha, str) and expected_sha and current_sha != expected_sha:
            raise ValueError("Current file sha256 does not match applied proposal; refusing revert")
        shutil.copy2(backup, target)
        reverted.append(
            {
                "path": raw_change.get("path"),
                "target_path": str(target),
                "backup_path": str(backup),
                "before_revert_sha256": current_sha,
                "after_revert_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            }
        )
    return {
        "mode": "exact_replace",
        "reverted_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "changes": reverted,
    }
