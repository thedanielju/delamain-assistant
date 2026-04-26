from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from delamain_backend.config import AppConfig

SCHEMA_VERSION = 1
MAX_NODE_SUMMARY_CHARS = 800


def generated_metadata_dir(config: AppConfig) -> Path:
    return config.paths.llm_workspace / "vault-index" / "generated"


def generated_metadata_path(config: AppConfig) -> Path:
    return generated_metadata_dir(config) / "metadata.json"


def load_generated_metadata(config: AppConfig) -> dict[str, Any]:
    path = generated_metadata_path(config)
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schema_version": SCHEMA_VERSION, "generated_at": None, "items": {}}
    if not isinstance(loaded, dict):
        return {"schema_version": SCHEMA_VERSION, "generated_at": None, "items": {}}
    items = loaded.get("items")
    if not isinstance(items, dict):
        items = {}
    return {
        "schema_version": loaded.get("schema_version", SCHEMA_VERSION),
        "generated_at": loaded.get("generated_at"),
        "items": {str(key): value for key, value in items.items() if isinstance(value, dict)},
        "relation_feedback": loaded.get("relation_feedback") if isinstance(loaded.get("relation_feedback"), dict) else {},
    }


def write_generated_metadata(config: AppConfig, metadata: dict[str, Any]) -> Path:
    path = generated_metadata_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "items": metadata.get("items", {}),
        "relation_feedback": metadata.get("relation_feedback", {}),
    }
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


def generated_item_for_node(metadata: dict[str, Any], node: dict[str, Any]) -> dict[str, Any] | None:
    path = str(node.get("path") or "")
    if not path:
        return None
    item = metadata.get("items", {}).get(path)
    return item if isinstance(item, dict) else None


def generated_metadata_state(metadata: dict[str, Any], node: dict[str, Any]) -> str:
    item = generated_item_for_node(metadata, node)
    if item is None:
        return "missing"
    node_sha = node.get("sha256")
    item_sha = item.get("sha256")
    if node_sha and item_sha and node_sha != item_sha:
        return "stale"
    return "fresh"


def apply_generated_metadata(node: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
    state = generated_metadata_state(metadata, node)
    node["generated_metadata_state"] = state
    node["summary_status"] = "fresh" if state == "fresh" else state
    item = generated_item_for_node(metadata, node)
    if state != "fresh" or item is None:
        node["generated_tags"] = []
        node["note_type"] = None
        node["stale_labels"] = []
        return node
    summary = str(item.get("summary") or "").strip()
    node["generated_summary"] = summary[:MAX_NODE_SUMMARY_CHARS]
    node["generated_tags"] = _string_list(item.get("tags"))[:12]
    node["note_type"] = _string_or_none(item.get("note_type"))
    node["stale_labels"] = _string_list(item.get("stale_labels"))[:8]
    node["owner_notes"] = _string_list(item.get("owner_notes"))[:8]
    node["duplicate_candidates"] = _clean_structured_list(item.get("duplicate_candidates"))[:8]
    node["decisions"] = _clean_text_list(item.get("decisions"))[:8]
    node["open_questions"] = _clean_text_list(item.get("open_questions"))[:8]
    node["relation_candidate_count"] = len(_clean_structured_list(item.get("relation_candidates")))
    node["generated_at"] = _string_or_none(item.get("generated_at"))
    return node


def generated_relation_key(from_path: str, to_path: str, relation_type: str) -> str:
    return f"{from_path}\u001f{to_path}\u001f{relation_type}"


def generated_relation_feedback(metadata: dict[str, Any]) -> dict[str, Any]:
    feedback = metadata.get("relation_feedback")
    return feedback if isinstance(feedback, dict) else {}


def set_generated_relation_feedback(
    metadata: dict[str, Any],
    *,
    from_path: str,
    to_path: str,
    relation_type: str,
    decision: str,
) -> dict[str, Any]:
    feedback = metadata.setdefault("relation_feedback", {})
    key = generated_relation_key(from_path, to_path, relation_type)
    feedback[key] = {
        "from_path": from_path,
        "to_path": to_path,
        "relation_type": relation_type,
        "decision": decision,
        "updated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }
    return feedback[key]


def generated_relation_candidates(metadata: dict[str, Any]) -> list[dict[str, Any]]:
    feedback = generated_relation_feedback(metadata)
    candidates: list[dict[str, Any]] = []
    items = metadata.get("items", {})
    if not isinstance(items, dict):
        return candidates
    for from_path, item in items.items():
        if not isinstance(item, dict):
            continue
        if item.get("sha256") and item.get("generated_at") is None:
            continue
        for raw in _clean_structured_list(item.get("relation_candidates")):
            to_path = str(raw.get("path") or raw.get("to_path") or "").strip()
            relation_type = str(raw.get("relation") or raw.get("relation_type") or "related").strip() or "related"
            if not to_path:
                continue
            key = generated_relation_key(str(from_path), to_path, relation_type)
            decision = feedback.get(key, {}).get("decision") if isinstance(feedback.get(key), dict) else None
            candidates.append(
                {
                    "from_path": str(from_path),
                    "to_path": to_path,
                    "relation_type": relation_type,
                    "reason": str(raw.get("reason") or "").strip(),
                    "confidence": _float_or_none(raw.get("confidence")),
                    "decision": decision or "candidate",
                    "key": key,
                }
            )
    return candidates


def fresh_generated_summary(config: AppConfig, path: str, sha256: str | None) -> str | None:
    metadata = load_generated_metadata(config)
    item = metadata.get("items", {}).get(path)
    if not isinstance(item, dict):
        return None
    if sha256 and item.get("sha256") and item.get("sha256") != sha256:
        return None
    summary = str(item.get("summary") or "").strip()
    return summary or None


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _clean_text_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip()[:500] for item in value if str(item).strip()]


def _clean_structured_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
