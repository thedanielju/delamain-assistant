from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from delamain_backend.agent.litellm_client import ModelClient
from delamain_backend.agent.runner import new_id
from delamain_backend.config import AppConfig
from delamain_backend.db import Database
from delamain_backend.errors import SensitiveLocked, ToolPolicyDenied
from delamain_backend.security.vault import (
    load_vault_graph,
    read_vault_note,
)
from delamain_backend.settings_store import SETTINGS_DEFAULTS
from delamain_backend.vault_generated import (
    generated_metadata_path,
    load_generated_metadata,
    write_generated_metadata,
)

MAX_ENRICHMENT_NOTES = 12
MAX_ENRICHMENT_NOTE_BYTES = 16_000


async def enrichment_status(config: AppConfig) -> dict[str, Any]:
    graph = load_vault_graph(config, limit=5000)
    nodes = [node for node in graph.get("nodes", []) if isinstance(node, dict)]
    counts = {"fresh": 0, "stale": 0, "missing": 0}
    for node in nodes:
        state = str(node.get("generated_metadata_state") or "missing")
        counts[state if state in counts else "missing"] += 1
    path = generated_metadata_path(config)
    return {
        "generated_path": str(path),
        "exists": path.exists(),
        "counts": counts,
        "node_count": len(nodes),
        "index_generated_at": graph.get("generated_at"),
        "next_candidates": [
            {
                "path": str(node.get("path")),
                "title": str(node.get("title") or node.get("path")),
                "state": str(node.get("generated_metadata_state") or "missing"),
                "source_type": str(node.get("source_type") or "vault_note"),
                "staleness_status": str(node.get("staleness_status") or "fresh"),
            }
            for node in _select_nodes(graph, paths=None, limit=12, force=False)
        ],
    }


async def run_enrichment(
    *,
    config: AppConfig,
    db: Database,
    model_client: ModelClient,
    paths: list[str] | None = None,
    limit: int = 4,
    force: bool = False,
    create_proposals: bool = True,
) -> dict[str, Any]:
    limit = max(1, min(limit, MAX_ENRICHMENT_NOTES))
    graph = load_vault_graph(config, limit=5000)
    selected = _select_nodes(graph, paths=paths, limit=limit, force=force)
    metadata = load_generated_metadata(config)
    items = metadata.setdefault("items", {})
    task_model = await _task_model_route(config, db)
    processed: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    errors: list[dict[str, str]] = []
    proposals_created: list[str] = []

    for node in selected:
        path = str(node.get("path") or "")
        try:
            note = read_vault_note(
                config,
                path,
                sensitive_unlocked=False,
                max_bytes=MAX_ENRICHMENT_NOTE_BYTES,
            )
        except (OSError, UnicodeDecodeError, ToolPolicyDenied, SensitiveLocked) as exc:
            skipped.append({"path": path, "reason": str(exc)})
            continue
        try:
            result = await _enrich_note_with_model(
                model_client=model_client,
                model_route=task_model,
                note={
                    "path": note.relative_path,
                    "title": note.title,
                    "source_type": note.source_type,
                    "tags": note.tags,
                    "sha256": note.sha256,
                    "content": note.content,
                    "truncated": note.truncated,
                    "graph_paths": [
                        str(candidate.get("path"))
                        for candidate in graph.get("nodes", [])
                        if isinstance(candidate, dict) and candidate.get("path") != note.relative_path
                    ][:200],
                },
            )
        except Exception as exc:
            errors.append({"path": path, "reason": str(exc)[:500]})
            continue
        item = {
            "path": note.relative_path,
            "title": note.title,
            "source_type": note.source_type,
            "sha256": note.sha256,
            "summary": result["summary"],
            "tags": result["tags"],
            "note_type": result["note_type"],
            "stale_labels": result["stale_labels"],
            "owner_notes": result["owner_notes"],
            "duplicate_candidates": result["duplicate_candidates"],
            "relation_candidates": result["relation_candidates"],
            "decisions": result["decisions"],
            "open_questions": result["open_questions"],
            "model_route": task_model,
            "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "evidence": {
                "source_truncated": note.truncated,
                "source_byte_count": note.byte_count,
            },
        }
        items[note.relative_path] = item
        processed.append(
            {
                "path": note.relative_path,
                "sha256": note.sha256,
                "tags": item["tags"],
                "note_type": item["note_type"],
            }
        )
        if create_proposals and note.source_type == "vault_note":
            proposal_id = await _create_tag_proposal_if_needed(db, note, item)
            if proposal_id:
                proposals_created.append(proposal_id)

    output_path = write_generated_metadata(config, metadata)
    return {
        "ok": not errors,
        "model_route": task_model,
        "processed": processed,
        "skipped": skipped,
        "errors": errors,
        "proposals_created": proposals_created,
        "generated_path": str(output_path),
    }


def _select_nodes(
    graph: dict[str, Any],
    *,
    paths: list[str] | None,
    limit: int,
    force: bool,
) -> list[dict[str, Any]]:
    nodes = [node for node in graph.get("nodes", []) if isinstance(node, dict)]
    if paths:
        wanted = {str(path) for path in paths}
        return [node for node in nodes if str(node.get("path")) in wanted][:limit]
    eligible = [
        node
        for node in nodes
        if force or str(node.get("generated_metadata_state") or "missing") != "fresh"
    ]
    return sorted(
        eligible,
        key=lambda node: (
            str(node.get("source_type") or "vault_note") == "vault_note",
            str(node.get("path") or "").lower(),
        ),
    )[:limit]


async def _task_model_route(config: AppConfig, db: Database) -> str:
    row = await db.fetchone("SELECT value FROM settings WHERE key = 'task_model'")
    if row is None:
        return str(SETTINGS_DEFAULTS["task_model"])
    try:
        value = json.loads(row["value"])
    except json.JSONDecodeError:
        return str(SETTINGS_DEFAULTS["task_model"])
    return value if isinstance(value, str) and value else config.models.fallback_cheap


async def _enrich_note_with_model(
    *,
    model_client: ModelClient,
    model_route: str,
    note: dict[str, Any],
) -> dict[str, Any]:
    messages = [
        {
            "role": "system",
            "content": (
                "You generate local vault metadata for DELAMAIN. Return only compact JSON with keys "
                "summary, tags, note_type, stale_labels, owner_notes, duplicate_candidates, "
                "relation_candidates, decisions, open_questions. Do not include markdown fences. "
                "Use source-grounded wording; do not invent facts."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "path": note["path"],
                    "title": note["title"],
                    "source_type": note["source_type"],
                    "existing_tags": note["tags"],
                    "truncated": note["truncated"],
                    "known_graph_paths": note.get("graph_paths", []),
                    "content": note["content"],
                },
                ensure_ascii=True,
            ),
        },
    ]
    result = await model_client.complete(model_route=model_route, messages=messages, tools=None)
    raw_text = str(result.get("text") or "")
    parsed = _parse_model_json(raw_text)
    return {
        "summary": _clean_summary(parsed.get("summary")),
        "tags": _clean_tags(parsed.get("tags")),
        "note_type": _clean_note_type(parsed.get("note_type")),
        "stale_labels": _clean_tags(parsed.get("stale_labels"))[:8],
        "owner_notes": _clean_path_list(parsed.get("owner_notes"))[:8],
        "duplicate_candidates": _clean_candidates(parsed.get("duplicate_candidates"))[:8],
        "relation_candidates": _clean_candidates(parsed.get("relation_candidates"))[:16],
        "decisions": _clean_text_list(parsed.get("decisions"))[:12],
        "open_questions": _clean_text_list(parsed.get("open_questions"))[:12],
    }


def _parse_model_json(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.lower().startswith("json"):
            stripped = stripped[4:].strip()
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise ValueError("Task model did not return valid enrichment JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError("Task model enrichment JSON must be an object")
    return parsed


def _clean_summary(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError("Task model enrichment JSON missing summary")
    return text[:1200]


def _clean_tags(value: Any) -> list[str]:
    raw = value if isinstance(value, list) else []
    tags: list[str] = []
    for item in raw:
        tag = str(item).strip().lower().replace(" ", "-")
        tag = tag.removeprefix("#")
        if tag and all(char.isalnum() or char in {"/", "-", "_"} for char in tag):
            tags.append(tag)
    return list(dict.fromkeys(tags))[:12]


def _clean_note_type(value: Any) -> str:
    text = str(value or "note").strip().lower().replace(" ", "_")
    return text[:60] or "note"


def _clean_path_list(value: Any) -> list[str]:
    raw = value if isinstance(value, list) else []
    paths: list[str] = []
    for item in raw:
        path = str(item).strip()
        if path and not path.startswith("/") and ".." not in path.split("/"):
            paths.append(path)
    return list(dict.fromkeys(paths))


def _clean_candidates(value: Any) -> list[dict[str, Any]]:
    raw = value if isinstance(value, list) else []
    candidates: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or item.get("to_path") or "").strip()
        if not path or path.startswith("/") or ".." in path.split("/"):
            continue
        relation = str(item.get("relation") or item.get("relation_type") or "related").strip()[:80] or "related"
        reason = str(item.get("reason") or "").strip()[:500]
        try:
            confidence = float(item.get("confidence"))
        except (TypeError, ValueError):
            confidence = None
        candidates.append(
            {
                "path": path,
                "relation": relation,
                "reason": reason,
                "confidence": confidence,
            }
        )
    return candidates[:16]


def _clean_text_list(value: Any) -> list[str]:
    raw = value if isinstance(value, list) else []
    return [str(item).strip()[:500] for item in raw if str(item).strip()]


async def _create_tag_proposal_if_needed(
    db: Database,
    note: Any,
    item: dict[str, Any],
) -> str | None:
    generated_tags = [tag for tag in item["tags"] if tag not in set(note.tags)]
    if not generated_tags:
        return None
    if not note.content:
        return None
    old_text, new_text = _frontmatter_tag_replacement(note.content, generated_tags)
    if not old_text or not new_text or note.content.count(old_text) != 1:
        return None
    existing = await db.fetchone(
        """
        SELECT id FROM vault_maintenance_proposals
        WHERE kind = 'generated_tag_suggestion'
          AND status IN ('proposed', 'accepted')
          AND paths_json = ?
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (json.dumps([note.relative_path], sort_keys=True),),
    )
    if existing is not None:
        return None
    proposal_id = new_id("vmp")
    await db.execute(
        """
        INSERT INTO vault_maintenance_proposals(
            id, conversation_id, kind, title, description, paths_json, payload_json, status
        )
        VALUES (?, NULL, 'generated_tag_suggestion', ?, ?, ?, ?, 'proposed')
        """,
        (
            proposal_id,
            f"Add generated tags to {note.title}",
            "AI enrichment suggested source-linked tags. Review the exact diff before applying.",
            json.dumps([note.relative_path], sort_keys=True),
            json.dumps(
                {
                    "action": "exact_replace",
                    "path": note.relative_path,
                    "old_text": old_text,
                    "new_text": new_text,
                    "expected_sha256": note.sha256,
                    "generated_tags": generated_tags,
                    "source": "vault_enrichment",
                },
                sort_keys=True,
            ),
        ),
    )
    return proposal_id


def _frontmatter_tag_replacement(content: str, generated_tags: list[str]) -> tuple[str | None, str | None]:
    tag_lines = "\n".join(f"  - {tag}" for tag in generated_tags)
    if content.startswith("---\n"):
        end = content.find("\n---\n", 4)
        if end == -1:
            return None, None
        frontmatter = content[: end + len("\n---\n")]
        if "\ntags:" in frontmatter:
            replacement = frontmatter.replace("\ntags:", f"\ntags:\n{tag_lines}", 1)
        else:
            replacement = frontmatter[:-5] + f"tags:\n{tag_lines}\n---\n"
        return frontmatter, replacement
    first_line_end = content.find("\n")
    if first_line_end == -1:
        old_text = content
    else:
        old_text = content[: first_line_end + 1]
    new_text = f"---\ntags:\n{tag_lines}\n---\n\n{old_text}"
    return old_text, new_text
