from __future__ import annotations

import json
import fnmatch
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from delamain_backend.config import AppConfig
from delamain_backend.errors import SensitiveLocked, ToolPolicyDenied
from delamain_backend.security.paths import PathPolicy

SCHEMA_VERSION = 1
MAX_NODE_SUMMARY_CHARS = 800


def generated_metadata_dir(config: AppConfig) -> Path:
    return config.paths.llm_workspace / "vault-index" / "generated"


def generated_metadata_path(config: AppConfig) -> Path:
    return generated_metadata_dir(config) / "metadata.json"


def load_generated_metadata(config: AppConfig) -> dict[str, Any]:
    path = generated_metadata_path(config)
    fallback = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": None,
        "items": {},
        "relation_feedback": {},
        "_relation_filter_context": _relation_filter_context(config),
    }
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fallback
    if not isinstance(loaded, dict):
        return fallback
    items = loaded.get("items")
    if not isinstance(items, dict):
        items = {}
    return {
        "schema_version": loaded.get("schema_version", SCHEMA_VERSION),
        "generated_at": loaded.get("generated_at"),
        "items": {str(key): value for key, value in items.items() if isinstance(value, dict)},
        "relation_feedback": loaded.get("relation_feedback") if isinstance(loaded.get("relation_feedback"), dict) else {},
        "_relation_filter_context": _relation_filter_context(config),
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


def generated_relation_candidates(
    metadata: dict[str, Any],
    *,
    allowed_paths: set[str] | None = None,
    source_sha_by_path: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    feedback = generated_relation_feedback(metadata)
    filter_context = metadata.get("_relation_filter_context")
    if isinstance(filter_context, dict):
        if allowed_paths is None and isinstance(filter_context.get("allowed_paths"), set):
            allowed_paths = filter_context["allowed_paths"]
        if source_sha_by_path is None and isinstance(filter_context.get("source_sha_by_path"), dict):
            source_sha_by_path = filter_context["source_sha_by_path"]
    candidates: list[dict[str, Any]] = []
    items = metadata.get("items", {})
    if not isinstance(items, dict):
        return candidates
    for from_path, item in items.items():
        if not isinstance(item, dict):
            continue
        from_path = str(from_path)
        if allowed_paths is not None and from_path not in allowed_paths:
            continue
        if not _generated_item_is_fresh_for_path(
            item,
            from_path=from_path,
            source_sha_by_path=source_sha_by_path,
        ):
            continue
        if item.get("sha256") and item.get("generated_at") is None:
            continue
        for raw in _clean_structured_list(item.get("relation_candidates")):
            to_path = str(raw.get("path") or raw.get("to_path") or "").strip()
            relation_type = str(raw.get("relation") or raw.get("relation_type") or "related").strip() or "related"
            if not to_path:
                continue
            if allowed_paths is not None and to_path not in allowed_paths:
                continue
            key = generated_relation_key(from_path, to_path, relation_type)
            decision = feedback.get(key, {}).get("decision") if isinstance(feedback.get(key), dict) else None
            candidates.append(
                {
                    "from_path": from_path,
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


def _generated_item_is_fresh_for_path(
    item: dict[str, Any],
    *,
    from_path: str,
    source_sha_by_path: dict[str, str] | None,
) -> bool:
    if source_sha_by_path is None:
        return True
    current_sha = source_sha_by_path.get(from_path)
    if not current_sha:
        return True
    item_sha = _string_or_none(item.get("sha256"))
    return item_sha == current_sha


def _relation_filter_context(config: AppConfig) -> dict[str, Any]:
    graph = _read_json_file(config.paths.llm_workspace / "vault-index" / "graph.json")
    if not isinstance(graph, dict):
        return {"allowed_paths": set(), "source_sha_by_path": {}}
    raw_nodes = graph.get("nodes")
    if not isinstance(raw_nodes, list):
        raw_nodes = []
    policy = PathPolicy(config)
    allowed_paths: set[str] = set()
    source_sha_by_path: dict[str, str] = {}
    for raw_node in raw_nodes:
        if not isinstance(raw_node, dict):
            continue
        path = _string_or_none(raw_node.get("path") or raw_node.get("file"))
        if path is None:
            continue
        source_type = _string_or_none(raw_node.get("source_type")) or "vault_note"
        policy_state = (_string_or_none(raw_node.get("policy_state")) or "allowed").lower()
        sensitivity = (_string_or_none(raw_node.get("sensitivity")) or "normal").lower()
        if policy_state in {"ignored", "excluded", "blocked", "private", "sensitive", "sensitive_locked"}:
            continue
        if sensitivity in {"private", "sensitive"}:
            continue
        if not _relation_path_allowed(
            config,
            policy,
            path,
            source_type=source_type,
        ):
            continue
        allowed_paths.add(path)
        sha = _string_or_none(raw_node.get("sha256"))
        if sha:
            source_sha_by_path[path] = sha
    return {"allowed_paths": allowed_paths, "source_sha_by_path": source_sha_by_path}


def _relation_path_allowed(
    config: AppConfig,
    policy: PathPolicy,
    raw_path: str,
    *,
    source_type: str,
) -> bool:
    try:
        rel = Path(raw_path)
        if rel.is_absolute() or any(part == ".." for part in rel.parts):
            return False
        if source_type.startswith("workspace_"):
            if not (raw_path.startswith("reference/") or raw_path.startswith("syllabi/")):
                return False
            if not raw_path.endswith("/document.md") and Path(raw_path).name != "document.md":
                return False
            absolute_path = (config.paths.llm_workspace / rel).expanduser().resolve(strict=False)
        else:
            if _is_ignored_relative_path(config, raw_path):
                return False
            absolute_path = (config.paths.vault / rel).expanduser().resolve(strict=False)
        policy.check(
            str(absolute_path),
            operation="read",
            sensitive_unlocked=False,
            allow_binary=False,
            must_exist=False,
        )
        return True
    except (OSError, SensitiveLocked, ToolPolicyDenied):
        return False


def _read_json_file(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _policy_ignore_patterns(config: AppConfig) -> list[str]:
    patterns: list[str] = []
    for path in [
        config.paths.vault / "vault_policy.md",
        config.paths.vault / ".modelignore",
        config.paths.vault / ".delamainignore",
    ]:
        is_policy_markdown = path.name == "vault_policy.md"
        if not path.exists():
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        in_fence = False
        fence_is_ignore = False
        in_ignore_section = not is_policy_markdown
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("```"):
                if in_fence:
                    in_fence = False
                    fence_is_ignore = False
                else:
                    language = stripped[3:].strip().lower()
                    in_fence = True
                    fence_is_ignore = language in {"", "gitignore", "ignore", "modelignore", "delamainignore"}
                continue
            if is_policy_markdown and stripped.startswith("## "):
                in_ignore_section = stripped.lstrip("#").strip().lower() == "ignore globs"
                continue
            if not stripped or stripped.startswith("#"):
                continue
            if in_fence:
                if fence_is_ignore:
                    patterns.append(stripped)
                continue
            if in_ignore_section and stripped.startswith("- ") and "`" in stripped:
                parts = stripped.split("`")
                for index in range(1, len(parts), 2):
                    candidate = parts[index].strip()
                    if candidate and _looks_like_ignore_pattern(candidate):
                        patterns.append(candidate)
                continue
            if stripped.startswith("- "):
                stripped = stripped[2:].strip()
            if "#" in stripped:
                stripped = stripped.split("#", 1)[0].strip()
            stripped = stripped.strip("`")
            if stripped and not is_policy_markdown:
                patterns.append(stripped.strip("`"))
    return list(dict.fromkeys(patterns))


def _looks_like_ignore_pattern(value: str) -> bool:
    return (
        "*" in value
        or "/" in value
        or "\\" in value
        or value.startswith(".")
        or value.startswith("*.")
    )


def _is_ignored_relative_path(config: AppConfig, relative_path: str) -> bool:
    normalized = relative_path.replace("\\", "/")
    for pattern in _policy_ignore_patterns(config):
        clean = pattern.strip().lstrip("/")
        if not clean:
            continue
        if fnmatch.fnmatch(normalized, clean) or fnmatch.fnmatch(Path(normalized).name, clean):
            return True
    return False


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
