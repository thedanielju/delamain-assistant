from __future__ import annotations

import hashlib
import json
import fnmatch
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from delamain_backend.config import AppConfig
from delamain_backend.errors import SensitiveLocked, ToolPolicyDenied
from delamain_backend.security.paths import PathPolicy
from delamain_backend.vault_generated import (
    apply_generated_metadata,
    fresh_generated_summary,
    generated_relation_candidates,
    load_generated_metadata,
)
from delamain_backend.vault_staleness import apply_staleness_metadata, vault_sync_conflict_paths

MAX_NOTE_PREVIEW_BYTES = 64_000
MAX_CONTEXT_NOTE_BYTES = 8_000
MAX_CONTEXT_TOTAL_BYTES = 32_000
MAX_CONTEXT_NOTES = 12


@dataclass(frozen=True)
class VaultNoteRead:
    path: Path
    relative_path: str
    title: str
    content: str
    byte_count: int
    sha256: str
    truncated: bool
    tags: list[str]
    backlinks: list[str]
    source_type: str = "vault_note"


def vault_index_dir(config: AppConfig) -> Path:
    return config.paths.llm_workspace / "vault-index"


def load_vault_graph(
    config: AppConfig,
    *,
    folder: str | None = None,
    tag: str | None = None,
    limit: int = 2000,
    sensitive_unlocked: bool = False,
) -> dict[str, Any]:
    limit = max(1, min(limit, 5000))
    graph_path = vault_index_dir(config) / "graph.json"
    manifest = _read_index_manifest(config)
    raw = _read_json_file(graph_path)
    if not isinstance(raw, dict):
        return {
            "nodes": [],
            "edges": [],
            "generated_at": None,
            "index": _index_status(config, manifest, missing=True),
            "filters": _graph_filters([]),
            "source": str(graph_path),
            "missing": True,
            "policy_exclusions": policy_exclusions(config)["exclusions"],
        }

    policy = PathPolicy(config)
    generated_metadata = load_generated_metadata(config)
    conflict_paths = vault_sync_conflict_paths(config)
    node_by_id: dict[str, dict[str, Any]] = {}
    allowed_ids: set[str] = set()
    known_paths: set[str] = set()
    raw_nodes = raw.get("nodes")
    if not isinstance(raw_nodes, list):
        raw_nodes = []
    for raw_node in raw_nodes:
        if len(node_by_id) >= limit:
            break
        node = _normalize_node(raw_node)
        if node is None:
            continue
        node = apply_generated_metadata(node, generated_metadata)
        node = apply_staleness_metadata(node, conflict_paths)
        relative_path = _allowed_graph_path(config, policy, node, sensitive_unlocked=sensitive_unlocked)
        if relative_path is None:
            continue
        if node["source_type"] == "vault_note" and _is_ignored_relative_path(config, relative_path):
            continue
        if folder and not relative_path.startswith(folder.rstrip("/") + "/"):
            continue
        if tag and tag not in node["tags"]:
            continue
        node["path"] = relative_path
        node["id"] = str(node.get("id") or relative_path)
        node_by_id[node["id"]] = node
        allowed_ids.add(node["id"])
        known_paths.add(relative_path)

    raw_edges = raw.get("edges")
    if not isinstance(raw_edges, list):
        raw_edges = []
    edges: list[dict[str, Any]] = []
    for raw_edge in raw_edges:
        edge = _normalize_edge(raw_edge)
        if edge is None:
            continue
        if edge["from"] in allowed_ids and edge["to"] in allowed_ids:
            edges.append(edge)
    edges.extend(_generated_relation_edges(generated_metadata, node_by_id))

    nodes = list(node_by_id.values())
    return {
        "nodes": nodes,
        "edges": edges,
        "generated_at": _string_or_none(raw.get("generated_at"))
        or _string_or_none(manifest.get("generated_at") if isinstance(manifest, dict) else None)
        or _mtime_iso(graph_path),
        "index": _index_status(config, manifest, missing=False),
        "filters": _graph_filters(nodes),
        "source": str(graph_path),
        "missing": False,
        "policy_exclusions": policy_exclusions(config)["exclusions"],
        "known_paths": sorted(known_paths),
    }


def vault_graph_neighborhood(
    config: AppConfig,
    raw_path: str,
    *,
    hops: int = 1,
    limit: int = 80,
    sensitive_unlocked: bool = False,
) -> dict[str, Any]:
    hops = max(1, min(hops, 4))
    limit = max(1, min(limit, 500))
    indexed = _load_filtered_graph_index(config, sensitive_unlocked=sensitive_unlocked)
    center_id = _resolve_index_node_id(indexed, raw_path)
    center = indexed["nodes"].get(center_id)
    if center is None:
        _raise_missing_or_policy_blocked(indexed, raw_path)
        raise FileNotFoundError("Vault graph node not found")

    adjacency = indexed["adjacency"]
    distances: dict[str, int] = {center_id: 0}
    frontier = deque([center_id])
    policy_omissions: dict[str, dict[str, Any]] = {}
    omitted_policy_edges = 0
    omitted_limit_nodes = 0

    while frontier:
        current_id = frontier.popleft()
        current_distance = distances[current_id]
        if current_distance >= hops:
            continue
        for neighbor_id in sorted(adjacency.get(current_id, set()), key=lambda node_id: _node_sort_key(indexed["nodes"].get(node_id), node_id)):
            if neighbor_id not in indexed["nodes"]:
                omission = indexed["omitted_nodes"].get(neighbor_id)
                if omission is not None:
                    policy_omissions.setdefault(neighbor_id, omission)
                    omitted_policy_edges += 1
                continue
            if neighbor_id in distances:
                continue
            if len(distances) >= limit:
                omitted_limit_nodes += 1
                continue
            distances[neighbor_id] = current_distance + 1
            frontier.append(neighbor_id)

    selected_ids = set(distances)
    nodes = [
        {**indexed["nodes"][node_id], "distance": distances[node_id]}
        for node_id in sorted(selected_ids, key=lambda node_id: (distances[node_id], _node_sort_key(indexed["nodes"].get(node_id), node_id)))
    ]
    edge_limit = max(limit * 4, limit)
    selected_edges: list[dict[str, Any]] = []
    omitted_limit_edges = 0
    for edge in indexed["edges"]:
        if edge["from"] in selected_ids and edge["to"] in selected_ids:
            if len(selected_edges) >= edge_limit:
                omitted_limit_edges += 1
                continue
            selected_edges.append(_edge_out(edge))

    return {
        "center": {**center, "distance": 0},
        "nodes": nodes,
        "edges": selected_edges,
        "hops": hops,
        "limit": limit,
        "omitted": {
            "nodes": omitted_limit_nodes + len(policy_omissions),
            "edges": omitted_limit_edges + omitted_policy_edges,
            "limit_nodes": omitted_limit_nodes,
            "limit_edges": omitted_limit_edges,
            "policy_nodes": len(policy_omissions),
            "policy_edges": omitted_policy_edges,
        },
        "policy_omissions": sorted(policy_omissions.values(), key=lambda item: str(item.get("path") or item.get("id")))[:50],
        "generated_at": indexed["generated_at"],
        "index": indexed["index"],
        "source": indexed["source"],
        "missing": indexed["missing"],
    }


def vault_graph_shortest_path(
    config: AppConfig,
    from_path: str,
    to_path: str,
    *,
    sensitive_unlocked: bool = False,
) -> dict[str, Any]:
    indexed = _load_filtered_graph_index(config, sensitive_unlocked=sensitive_unlocked)
    from_id = _resolve_index_node_id(indexed, from_path)
    to_id = _resolve_index_node_id(indexed, to_path)
    if from_id not in indexed["nodes"]:
        _raise_missing_or_policy_blocked(indexed, from_path)
        raise FileNotFoundError("Vault graph source node not found")
    if to_id not in indexed["nodes"]:
        _raise_missing_or_policy_blocked(indexed, to_path)
        raise FileNotFoundError("Vault graph target node not found")

    previous: dict[str, tuple[str, dict[str, Any]]] = {}
    visited = {from_id}
    queue = deque([from_id])
    policy_omissions: dict[str, dict[str, Any]] = {}
    omitted_policy_edges = 0

    while queue and to_id not in visited:
        current_id = queue.popleft()
        for neighbor_id in sorted(indexed["adjacency"].get(current_id, set()), key=lambda node_id: _node_sort_key(indexed["nodes"].get(node_id), node_id)):
            if neighbor_id not in indexed["nodes"]:
                omission = indexed["omitted_nodes"].get(neighbor_id)
                if omission is not None:
                    policy_omissions.setdefault(neighbor_id, omission)
                    omitted_policy_edges += 1
                continue
            if neighbor_id in visited:
                continue
            edge = _edge_between(indexed["edge_by_pair"], current_id, neighbor_id)
            if edge is None:
                continue
            visited.add(neighbor_id)
            previous[neighbor_id] = (current_id, edge)
            queue.append(neighbor_id)

    if to_id not in visited:
        return {
            "from": indexed["nodes"][from_id],
            "to": indexed["nodes"][to_id],
            "found": False,
            "nodes": [],
            "edges": [],
            "hops": None,
            "omitted": {
                "nodes": len(policy_omissions),
                "edges": omitted_policy_edges,
                "policy_nodes": len(policy_omissions),
                "policy_edges": omitted_policy_edges,
            },
            "policy_omissions": sorted(policy_omissions.values(), key=lambda item: str(item.get("path") or item.get("id")))[:50],
            "generated_at": indexed["generated_at"],
            "index": indexed["index"],
            "source": indexed["source"],
            "missing": indexed["missing"],
        }

    path_ids = [to_id]
    path_edges: list[dict[str, Any]] = []
    while path_ids[-1] != from_id:
        prior_id, edge = previous[path_ids[-1]]
        path_edges.append(edge)
        path_ids.append(prior_id)
    path_ids.reverse()
    path_edges.reverse()
    return {
        "from": indexed["nodes"][from_id],
        "to": indexed["nodes"][to_id],
        "found": True,
        "nodes": [indexed["nodes"][node_id] for node_id in path_ids],
        "edges": [_edge_out(edge) for edge in path_edges],
        "hops": len(path_edges),
        "omitted": {
            "nodes": len(policy_omissions),
            "edges": omitted_policy_edges,
            "policy_nodes": len(policy_omissions),
            "policy_edges": omitted_policy_edges,
        },
        "policy_omissions": sorted(policy_omissions.values(), key=lambda item: str(item.get("path") or item.get("id")))[:50],
        "generated_at": indexed["generated_at"],
        "index": indexed["index"],
        "source": indexed["source"],
        "missing": indexed["missing"],
    }


def policy_exclusions(
    config: AppConfig,
    *,
    conversation_sensitive_unlocked: bool = False,
) -> dict[str, Any]:
    index_policy = _read_json_file(vault_index_dir(config) / "policy-exclusions.json")
    indexed: list[dict[str, Any]] = []
    if isinstance(index_policy, dict):
        raw_exclusions = index_policy.get("exclusions")
        if isinstance(raw_exclusions, list):
            indexed = [item for item in raw_exclusions if isinstance(item, dict)]
    policy_patterns = _policy_ignore_patterns(config)
    policy_items = [
        {
            "kind": "vault_policy_glob",
            "path": pattern,
            "reason": "User-editable vault policy ignore glob",
        }
        for pattern in policy_patterns
    ]
    return {
        "sensitive_locked": not conversation_sensitive_unlocked,
        "roots": {
            "vault": str(config.paths.vault),
            "llm_workspace": str(config.paths.llm_workspace),
            "sensitive": str(config.paths.sensitive),
        },
        "exclusions": [
            *policy_items,
            {
                "kind": "root",
                "path": str(config.paths.sensitive),
                "reason": "Sensitive is excluded from vault graph and context by default",
            },
            {
                "kind": "restricted_patterns",
                "patterns": [
                    ".env*",
                    "private key files",
                    "*.pem",
                    "*.key",
                    "*oauth*",
                    "*token*",
                    "*credential*",
                    "*secret*",
                    "binary files",
                ],
                "reason": "Backend path policy rejects restricted or binary paths",
            },
            *indexed,
        ],
    }


def known_vault_paths(config: AppConfig, *, sensitive_unlocked: bool = False) -> set[str]:
    graph = load_vault_graph(config, sensitive_unlocked=sensitive_unlocked)
    paths = graph.get("known_paths")
    if isinstance(paths, list):
        return {str(path) for path in paths}
    return {str(node["path"]) for node in graph.get("nodes", []) if isinstance(node, dict)}


def graph_node_for_path(
    config: AppConfig,
    raw_path: str,
    *,
    sensitive_unlocked: bool = False,
) -> dict[str, Any] | None:
    target = str(raw_path or "").strip()
    if not target:
        return None
    graph = load_vault_graph(config, sensitive_unlocked=sensitive_unlocked, limit=5000)
    for node in graph.get("nodes", []):
        if not isinstance(node, dict):
            continue
        if target in {str(node.get("path")), str(node.get("id")), str(node.get("document_md") or "")}:
            return node
    return None


def read_vault_note(
    config: AppConfig,
    raw_path: str,
    *,
    sensitive_unlocked: bool,
    max_bytes: int = MAX_NOTE_PREVIEW_BYTES,
    require_indexed: bool = True,
) -> VaultNoteRead:
    policy = PathPolicy(config)
    node = graph_node_for_path(config, raw_path, sensitive_unlocked=sensitive_unlocked)
    if require_indexed and node is None:
        raise ToolPolicyDenied("Vault note is not present in the deterministic index")
    source_type = str(node.get("source_type") if node else "vault_note")
    relative_path = str(node.get("path") if node else raw_path)
    if source_type == "vault_note" and _is_ignored_relative_path(config, relative_path):
        raise ToolPolicyDenied("Vault note is excluded by vault policy")
    absolute_path = _absolute_context_path(config, relative_path, source_type)
    decision = policy.check(
        str(absolute_path),
        operation="read",
        sensitive_unlocked=sensitive_unlocked,
        allow_binary=False,
    )
    data = decision.path.read_bytes()
    truncated = len(data) > max_bytes
    bounded = data[:max_bytes]
    content = bounded.decode("utf-8", errors="replace")
    tags = _string_list(node.get("tags")) if node else _tags_for_path(config, relative_path)
    return VaultNoteRead(
        path=decision.path,
        relative_path=relative_path,
        title=_title_for_path(relative_path, content),
        content=content,
        byte_count=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        truncated=truncated,
        tags=tags,
        backlinks=_backlinks_for_path(config, relative_path),
        source_type=source_type,
    )


def preview_context_candidates(
    config: AppConfig,
    prompt: str,
    *,
    limit: int = 8,
    sensitive_unlocked: bool = False,
) -> list[dict[str, Any]]:
    graph = load_vault_graph(config, sensitive_unlocked=sensitive_unlocked, limit=5000)
    nodes = [node for node in graph.get("nodes", []) if isinstance(node, dict)]
    if not nodes:
        return []
    query_terms = _query_terms(prompt)
    expanded_terms = _expand_query_terms(query_terms)
    scored: list[tuple[int, dict[str, Any], list[str]]] = []
    for node in nodes:
        if _is_context_payload_blocked(node):
            continue
        score, reasons = _score_node_for_terms(node, query_terms, expanded_terms)
        if score <= 0:
            continue
        scored.append((score, node, reasons))
    scored.sort(key=lambda item: (-item[0], str(item[1].get("path") or "").lower()))
    candidates: list[dict[str, Any]] = []
    for score, node, reasons in scored[: max(1, min(limit, MAX_CONTEXT_NOTES))]:
        byte_count = _node_byte_count(node)
        summary = fresh_generated_summary(config, str(node.get("path")), str(node.get("sha256") or ""))
        mode = "full_note" if byte_count is not None and byte_count <= MAX_CONTEXT_NOTE_BYTES else "summary"
        candidates.append(
            {
                "id": str(node.get("path")),
                "path": str(node.get("path")),
                "title": str(node.get("title") or node.get("path")),
                "mode": mode,
                "preview": summary if mode == "summary" else None,
                "reason": reasons[0] if reasons else "deterministic_match",
                "reasons": reasons,
                "score": score,
                "estimated_tokens": _estimate_tokens(byte_count),
                "sha256": node.get("sha256"),
                "stale": False,
                "pinned": False,
                "source_type": node.get("source_type"),
                "category": node.get("category"),
                "generated_tags": node.get("generated_tags", []),
                "note_type": node.get("note_type"),
                "summary_status": node.get("summary_status"),
                "policy": {"sensitive": False, "restricted": False},
            }
        )
    return candidates


def resolve_vault_relative_path(
    config: AppConfig,
    raw_path: str,
    *,
    sensitive_unlocked: bool,
    policy: PathPolicy | None = None,
    must_exist: bool,
) -> str:
    value = str(raw_path or "").strip()
    if not value:
        raise ToolPolicyDenied("Vault path is required")
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        if any(part == ".." for part in candidate.parts):
            raise ToolPolicyDenied("Vault path must stay inside the vault")
        candidate = config.paths.vault / candidate
    decision = (policy or PathPolicy(config)).check(
        str(candidate),
        operation="read",
        sensitive_unlocked=sensitive_unlocked,
        allow_binary=False,
        must_exist=must_exist,
    )
    vault_root = config.paths.vault.expanduser().resolve(strict=False)
    try:
        return decision.path.relative_to(vault_root).as_posix()
    except ValueError as exc:
        raise ToolPolicyDenied("Path is outside the configured vault") from exc


def load_selected_context_notes(
    config: AppConfig,
    paths: list[str],
    *,
    sensitive_unlocked: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    items: list[dict[str, Any]] = []
    prompt_blocks: list[str] = []
    used_bytes = 0
    for raw_path in paths[:MAX_CONTEXT_NOTES]:
        try:
            note = read_vault_note(
                config,
                raw_path,
                sensitive_unlocked=sensitive_unlocked,
                max_bytes=min(MAX_CONTEXT_NOTE_BYTES, MAX_CONTEXT_TOTAL_BYTES - used_bytes),
            )
        except (OSError, UnicodeDecodeError, ToolPolicyDenied, SensitiveLocked) as exc:
            items.append(
                {
                    "path": raw_path,
                    "mode": "vault_note_pin",
                    "included": False,
                    "missing": isinstance(exc, OSError),
                    "byte_count": None,
                    "sha256": None,
                    "title": None,
                    "reason": str(exc),
                }
            )
            continue
        if used_bytes >= MAX_CONTEXT_TOTAL_BYTES:
            items.append(_note_context_item(note, included=False, reason="Context budget exhausted"))
            continue
        summary = fresh_generated_summary(config, note.relative_path, note.sha256)
        content = note.content
        mode = "vault_note_pin"
        reason = "Pinned vault note"
        if note.truncated and summary:
            content = summary
            mode = "generated_summary"
            reason = "Pinned vault note summarized from generated metadata"
        used_bytes += len(content.encode("utf-8"))
        items.append(
            _note_context_item(
                note,
                included=True,
                reason=reason,
                mode=mode,
            )
        )
        label = "Workspace document" if note.source_type.startswith("workspace_") else "Vault note"
        prompt_blocks.append(f"## {note.title}\n{label}: {note.relative_path}\nMode: {mode}\n\n{content}")
    prompt_messages = []
    if prompt_blocks:
        prompt_messages.append(
            {
                "role": "system",
                "content": "Selected vault context for this run:\n\n"
                + "\n\n---\n\n".join(prompt_blocks),
            }
        )
    return items, prompt_messages


def _load_filtered_graph_index(
    config: AppConfig,
    *,
    sensitive_unlocked: bool,
) -> dict[str, Any]:
    graph_path = vault_index_dir(config) / "graph.json"
    manifest = _read_index_manifest(config)
    raw = _read_json_file(graph_path)
    if not isinstance(raw, dict):
        return {
            "nodes": {},
            "omitted_nodes": {},
            "aliases": {},
            "edges": [],
            "adjacency": {},
            "edge_by_pair": {},
            "generated_at": None,
            "index": _index_status(config, manifest, missing=True),
            "source": str(graph_path),
            "missing": True,
        }

    policy = PathPolicy(config)
    generated_metadata = load_generated_metadata(config)
    conflict_paths = vault_sync_conflict_paths(config)
    nodes: dict[str, dict[str, Any]] = {}
    omitted_nodes: dict[str, dict[str, Any]] = {}
    aliases: dict[str, str] = {}
    raw_nodes = raw.get("nodes") if isinstance(raw.get("nodes"), list) else []
    for raw_node in raw_nodes:
        node = _normalize_node(raw_node)
        if node is None:
            continue
        node = apply_generated_metadata(node, generated_metadata)
        node = apply_staleness_metadata(node, conflict_paths)
        node["id"] = str(node.get("id") or node["path"])
        relative_path = _allowed_graph_path(config, policy, node, sensitive_unlocked=sensitive_unlocked)
        omission_reason = _graph_policy_omission_reason(config, node, relative_path)
        if omission_reason is not None:
            omitted_nodes[node["id"]] = _policy_omission(node, omission_reason)
            for alias in _node_lookup_aliases(node):
                aliases[alias] = node["id"]
            continue
        node["path"] = str(relative_path)
        nodes[node["id"]] = node
        for alias in _node_lookup_aliases(node):
            aliases[alias] = node["id"]

    raw_edges = raw.get("edges") if isinstance(raw.get("edges"), list) else []
    edges: list[dict[str, Any]] = []
    adjacency: dict[str, set[str]] = {}
    edge_by_pair: dict[tuple[str, str], dict[str, Any]] = {}
    for raw_edge in raw_edges:
        edge = _normalize_edge(raw_edge)
        if edge is None:
            continue
        from_id = aliases.get(edge["from"], edge["from"])
        to_id = aliases.get(edge["to"], edge["to"])
        edge = {**edge, "from": from_id, "to": to_id}
        if from_id not in nodes and from_id not in omitted_nodes:
            continue
        if to_id not in nodes and to_id not in omitted_nodes:
            continue
        adjacency.setdefault(from_id, set()).add(to_id)
        adjacency.setdefault(to_id, set()).add(from_id)
        if from_id in nodes and to_id in nodes:
            edges.append(edge)
            pair = tuple(sorted((from_id, to_id)))
            edge_by_pair.setdefault(pair, edge)
    for edge in _generated_relation_edges(generated_metadata, nodes):
        from_id = edge["from"]
        to_id = edge["to"]
        if from_id not in nodes or to_id not in nodes:
            continue
        edges.append(edge)
        adjacency.setdefault(from_id, set()).add(to_id)
        adjacency.setdefault(to_id, set()).add(from_id)
        edge_by_pair.setdefault(tuple(sorted((from_id, to_id))), edge)

    return {
        "nodes": nodes,
        "omitted_nodes": omitted_nodes,
        "aliases": aliases,
        "edges": edges,
        "adjacency": adjacency,
        "edge_by_pair": edge_by_pair,
        "generated_at": _string_or_none(raw.get("generated_at"))
        or _string_or_none(manifest.get("generated_at") if isinstance(manifest, dict) else None)
        or _mtime_iso(graph_path),
        "index": _index_status(config, manifest, missing=False),
        "source": str(graph_path),
        "missing": False,
    }


def _resolve_index_node_id(indexed: dict[str, Any], raw_path: str) -> str:
    target = str(raw_path or "").strip()
    if not target:
        raise FileNotFoundError("Vault graph node path is required")
    aliases = indexed["aliases"]
    if target in aliases:
        return aliases[target]
    return target


def _raise_missing_or_policy_blocked(indexed: dict[str, Any], raw_path: str) -> None:
    target = str(raw_path or "").strip()
    node_id = indexed["aliases"].get(target, target)
    omission = indexed["omitted_nodes"].get(node_id)
    if omission is None:
        return
    if omission.get("reason") == "sensitive_locked":
        raise SensitiveLocked("Sensitive vault is locked for this conversation")
    raise ToolPolicyDenied("Vault graph node is excluded by policy")


def _graph_policy_omission_reason(
    config: AppConfig,
    node: dict[str, Any],
    relative_path: str | None,
) -> str | None:
    if relative_path is None:
        source_type = str(node.get("source_type") or "vault_note")
        raw_path = str(node.get("path") or "")
        if source_type == "vault_note":
            absolute_path = (config.paths.vault / raw_path).expanduser().resolve(strict=False)
            try:
                absolute_path.relative_to(config.paths.sensitive.expanduser().resolve(strict=False))
                return "sensitive_locked"
            except ValueError:
                pass
        return "path_policy"
    policy_state = str(node.get("policy_state") or "allowed")
    if policy_state in {"ignored", "excluded", "blocked"}:
        return policy_state
    if node["source_type"] == "vault_note" and _is_ignored_relative_path(config, relative_path):
        return "ignored"
    return None


def _policy_omission(node: dict[str, Any], reason: str) -> dict[str, Any]:
    raw_path = str(node.get("path") or node.get("id"))
    redacted = reason in {"path_policy", "sensitive_locked"} or _looks_secret_like(raw_path)
    return {
        "id": None if redacted else str(node.get("id") or node.get("path")),
        "path": None if redacted else raw_path,
        "title": "Policy-excluded node" if redacted else str(node.get("title") or raw_path),
        "source_type": str(node.get("source_type") or "vault_note"),
        "reason": reason,
    }


def _looks_secret_like(path: str) -> bool:
    name = Path(path).name.lower()
    suffix = Path(path).suffix.lower()
    if name == ".env" or name.startswith(".env."):
        return True
    if suffix in {".pem", ".key", ".p12", ".pfx"}:
        return True
    return any(marker in name for marker in ["oauth", "token", "credential", "secret"])


def _node_lookup_aliases(node: dict[str, Any]) -> set[str]:
    aliases = {
        str(node.get("id") or ""),
        str(node.get("path") or ""),
        str(node.get("document_md") or ""),
    }
    return {alias for alias in aliases if alias}


def _node_sort_key(node: dict[str, Any] | None, fallback: str) -> tuple[str, str]:
    if node is None:
        return ("", fallback.lower())
    return (str(node.get("title") or "").lower(), str(node.get("path") or fallback).lower())


def _edge_between(
    edge_by_pair: dict[tuple[str, str], dict[str, Any]],
    left_id: str,
    right_id: str,
) -> dict[str, Any] | None:
    return edge_by_pair.get(tuple(sorted((left_id, right_id))))


def _edge_out(edge: dict[str, Any]) -> dict[str, Any]:
    return {
        **edge,
        "id": f"{edge['from']}->{edge['to']}:{edge['kind']}",
        "reason": edge["kind"],
    }


def _generated_relation_edges(
    metadata: dict[str, Any],
    nodes_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    by_path = {str(node.get("path")): node_id for node_id, node in nodes_by_id.items()}
    edges: list[dict[str, Any]] = []
    for candidate in generated_relation_candidates(metadata):
        decision = str(candidate.get("decision") or "candidate")
        if decision == "rejected":
            continue
        from_id = by_path.get(str(candidate.get("from_path")))
        to_id = by_path.get(str(candidate.get("to_path")))
        if not from_id or not to_id or from_id == to_id:
            continue
        accepted = decision == "accepted"
        edges.append(
            {
                "from": from_id,
                "to": to_id,
                "kind": "accepted_generated" if accepted else "generated_candidate",
                "generated": True,
                "accepted": accepted,
                "relation_type": candidate.get("relation_type"),
                "reason": candidate.get("reason"),
                "confidence": candidate.get("confidence"),
            }
        )
    return edges


def _note_context_item(
    note: VaultNoteRead,
    *,
    included: bool,
    reason: str,
    mode: str = "vault_note_pin",
) -> dict[str, Any]:
    return {
        "path": str(note.path),
        "relative_path": note.relative_path,
        "mode": mode,
        "included": included,
        "missing": False,
        "byte_count": note.byte_count,
        "sha256": note.sha256,
        "title": note.title,
        "truncated": note.truncated,
        "reason": reason,
        "source_type": note.source_type,
    }


def _normalize_node(raw_node: Any) -> dict[str, Any] | None:
    if not isinstance(raw_node, dict):
        return None
    path = _string_or_none(raw_node.get("path") or raw_node.get("file"))
    if not path:
        return None
    title = _string_or_none(raw_node.get("title")) or _title_from_relative_path(path)
    tags = _string_list(raw_node.get("tags"))
    aliases = _string_list(raw_node.get("aliases"))
    source_type = _string_or_none(raw_node.get("source_type")) or "vault_note"
    return {
        "id": _string_or_none(raw_node.get("id")) or path,
        "path": path,
        "title": title,
        "tags": tags,
        "aliases": aliases,
        "folder": _string_or_none(raw_node.get("folder")) or str(Path(path).parent).replace("\\", "/"),
        "mtime": _string_or_none(raw_node.get("mtime") or raw_node.get("modified_at")) or "",
        "bytes": raw_node.get("bytes") if isinstance(raw_node.get("bytes"), int) else raw_node.get("size_bytes") if isinstance(raw_node.get("size_bytes"), int) else None,
        "sha256": _string_or_none(raw_node.get("sha256")),
        "source_type": source_type,
        "source_root": _string_or_none(raw_node.get("source_root")),
        "category": _string_or_none(raw_node.get("category")),
        "bundle_id": _string_or_none(raw_node.get("bundle_id")),
        "document_md": _string_or_none(raw_node.get("document_md")),
        "source_path": _string_or_none(raw_node.get("source_path")),
        "converter": _string_or_none(raw_node.get("converter")),
        "status": _string_or_none(raw_node.get("status")),
        "placement": _string_or_none(raw_node.get("placement")),
        "pinned": bool(raw_node.get("pinned")),
        "headings": raw_node.get("headings") if isinstance(raw_node.get("headings"), list) else [],
        "incoming_link_count": raw_node.get("incoming_link_count") if isinstance(raw_node.get("incoming_link_count"), int) else 0,
        "dangling_link_count": raw_node.get("dangling_link_count") if isinstance(raw_node.get("dangling_link_count"), int) else 0,
        "archive_state": _string_or_none(raw_node.get("archive_state")),
        "policy_state": _string_or_none(raw_node.get("policy_state")) or "allowed",
        "warnings": _string_list(raw_node.get("warnings")),
    }


def _normalize_edge(raw_edge: Any) -> dict[str, Any] | None:
    if not isinstance(raw_edge, dict):
        return None
    from_id = _string_or_none(raw_edge.get("from") or raw_edge.get("source"))
    to_id = _string_or_none(raw_edge.get("to") or raw_edge.get("target"))
    if not from_id or not to_id:
        return None
    kind = _string_or_none(raw_edge.get("kind") or raw_edge.get("type")) or "wikilink"
    if kind not in {
        "wikilink",
        "markdown_link",
        "markdown",
        "embed",
        "backlink",
        "tag",
        "property",
        "generated_candidate",
        "accepted_generated",
        "rejected_generated",
    }:
        kind = "wikilink"
    if kind == "markdown":
        kind = "markdown_link"
    return {"from": from_id, "to": to_id, "kind": kind}


def _allowed_graph_path(
    config: AppConfig,
    policy: PathPolicy,
    node: dict[str, Any],
    *,
    sensitive_unlocked: bool,
) -> str | None:
    source_type = str(node.get("source_type") or "vault_note")
    raw_path = str(node.get("path") or "")
    if source_type.startswith("workspace_"):
        try:
            path = _absolute_context_path(config, raw_path, source_type)
            policy.check(str(path), operation="read", sensitive_unlocked=sensitive_unlocked, allow_binary=False, must_exist=False)
            return raw_path
        except (ToolPolicyDenied, SensitiveLocked, OSError):
            return None
    return _allowed_relative_path(
        config,
        policy,
        raw_path,
        sensitive_unlocked=sensitive_unlocked,
        must_exist=False,
    )


def _absolute_context_path(config: AppConfig, relative_path: str, source_type: str) -> Path:
    rel = Path(relative_path)
    if rel.is_absolute() or any(part == ".." for part in rel.parts):
        raise ToolPolicyDenied("Context path must be relative to an allowed root")
    if source_type.startswith("workspace_"):
        if not (relative_path.startswith("reference/") or relative_path.startswith("syllabi/")):
            raise ToolPolicyDenied("Workspace graph context must come from reference or syllabi")
        if not relative_path.endswith("/document.md") and Path(relative_path).name != "document.md":
            raise ToolPolicyDenied("Workspace graph context can only read converted document.md")
        return (config.paths.llm_workspace / rel).expanduser().resolve(strict=True)
    return (config.paths.vault / rel).expanduser().resolve(strict=True)


def _allowed_relative_path(
    config: AppConfig,
    policy: PathPolicy,
    raw_path: str,
    *,
    sensitive_unlocked: bool,
    must_exist: bool,
) -> str | None:
    try:
        return resolve_vault_relative_path(
            config,
            raw_path,
            sensitive_unlocked=sensitive_unlocked,
            policy=policy,
            must_exist=must_exist,
        )
    except (ToolPolicyDenied, SensitiveLocked, OSError):
        return None


def _backlinks_for_path(config: AppConfig, relative_path: str) -> list[str]:
    backlinks = _read_json_file(vault_index_dir(config) / "backlinks.json")
    if not isinstance(backlinks, dict):
        return []
    raw = backlinks.get(relative_path)
    if raw is None:
        raw = backlinks.get(str(config.paths.vault / relative_path))
    return _string_list(raw)


def _tags_for_path(config: AppConfig, relative_path: str) -> list[str]:
    tags = _read_json_file(vault_index_dir(config) / "tags.json")
    if not isinstance(tags, dict):
        return []
    raw = tags.get(relative_path)
    if raw is None:
        raw = tags.get(str(config.paths.vault / relative_path))
    return _string_list(raw)


def _read_json_file(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _read_index_manifest(config: AppConfig) -> dict[str, Any]:
    manifest = _read_json_file(vault_index_dir(config) / "_manifest.json")
    return manifest if isinstance(manifest, dict) else {}


def _index_status(config: AppConfig, manifest: dict[str, Any], *, missing: bool) -> dict[str, Any]:
    generated_at = _string_or_none(manifest.get("generated_at"))
    stale_reasons: list[str] = []
    if missing:
        stale_reasons.append("missing_graph")
    source_root = _string_or_none(manifest.get("source_root"))
    if source_root and Path(source_root).expanduser().resolve(strict=False) != config.paths.vault.expanduser().resolve(strict=False):
        stale_reasons.append("source_root_mismatch")
    current_policy_hash = _policy_hash(config)
    manifest_policy_hash = _string_or_none(manifest.get("policy_hash"))
    if manifest_policy_hash and manifest_policy_hash != current_policy_hash:
        stale_reasons.append("policy_hash_mismatch")
    if generated_at:
        try:
            generated = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
            if datetime.now(timezone.utc) - generated.astimezone(timezone.utc) > timedelta(days=7):
                stale_reasons.append("older_than_7_days")
        except ValueError:
            stale_reasons.append("invalid_generated_at")
    return {
        "status": "missing" if missing else ("stale" if stale_reasons else "ok"),
        "schema_version": manifest.get("schema_version"),
        "generated_at": generated_at,
        "policy_hash": manifest_policy_hash,
        "current_policy_hash": current_policy_hash,
        "stale": bool(stale_reasons),
        "stale_reasons": stale_reasons,
        "indexed_count": manifest.get("indexed_count", manifest.get("file_count", 0)),
        "vault_note_count": manifest.get("vault_note_count"),
        "workspace_bundle_count": manifest.get("workspace_bundle_count", 0),
        "skipped_count": manifest.get("skipped_count", len(manifest.get("skipped_paths", []))),
        "warnings": manifest.get("warnings", []),
    }


def _graph_filters(nodes: list[dict[str, Any]]) -> dict[str, list[str]]:
    def values(key: str) -> list[str]:
        return sorted({str(node.get(key)) for node in nodes if node.get(key)})

    return {
        "source_types": values("source_type"),
        "folders": values("folder"),
        "categories": values("category"),
        "statuses": values("status"),
        "placements": values("placement"),
        "archive_states": values("archive_state"),
        "staleness_statuses": values("staleness_status"),
        "sync_statuses": values("sync_status"),
    }


def _policy_hash(config: AppConfig) -> str:
    digest = hashlib.sha256()
    for path in [_vault_policy_path(config), config.paths.vault / ".modelignore", config.paths.vault / ".delamainignore"]:
        if not path.exists():
            continue
        try:
            data = path.read_bytes()
        except OSError:
            continue
        digest.update(str(path).encode("utf-8"))
        digest.update(data)
    return f"sha256:{digest.hexdigest()}"


def _is_context_payload_blocked(node: dict[str, Any]) -> bool:
    source_type = str(node.get("source_type") or "vault_note")
    status = str(node.get("status") or "fresh")
    if source_type.startswith("workspace_") and status in {"failed", "needs_ocr", "needs_reprocess"}:
        return True
    return False


def _title_for_path(relative_path: str, content: str) -> str:
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip() or _title_from_relative_path(relative_path)
    return _title_from_relative_path(relative_path)


def _title_from_relative_path(path: str) -> str:
    return Path(path).stem.replace("_", " ").replace("-", " ").strip() or path


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _mtime_iso(path: Path) -> str | None:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()
    except OSError:
        return None


def _vault_policy_path(config: AppConfig) -> Path:
    return config.paths.vault / "vault_policy.md"


def _policy_ignore_patterns(config: AppConfig) -> list[str]:
    patterns: list[str] = []
    for path in [
        _vault_policy_path(config),
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


def _query_terms(prompt: str) -> list[str]:
    import re

    terms = [
        term.lower()
        for term in re.findall(r"[A-Za-z0-9][A-Za-z0-9_/-]{2,}", prompt)
        if term.lower()
        not in {
            "the",
            "and",
            "for",
            "with",
            "that",
            "this",
            "from",
            "about",
            "what",
            "when",
            "where",
            "how",
            "can",
            "you",
            "delamain",
        }
    ]
    return list(dict.fromkeys(terms))[:24]


def _expand_query_terms(terms: list[str]) -> set[str]:
    synonyms = {
        "schedule": {"calendar", "timeline", "class", "classes", "due", "deadline", "deadlines", "daily"},
        "today": {"daily", "timeline", "schedule", "calendar"},
        "school": {"class", "classes", "course", "courses", "exam", "assignment"},
        "memory": {"vault", "graph", "context", "summary", "summaries", "notes"},
        "graph": {"vault", "index", "backlink", "backlinks", "context"},
        "workout": {"fitness", "training", "physique"},
    }
    expanded = set(terms)
    for term in terms:
        expanded.update(synonyms.get(term, set()))
    return expanded


def _score_node_for_terms(
    node: dict[str, Any],
    query_terms: list[str],
    expanded_terms: set[str],
) -> tuple[int, list[str]]:
    haystacks = {
        "title": str(node.get("title") or "").lower(),
        "path": str(node.get("path") or "").lower(),
        "folder": str(node.get("folder") or "").lower(),
        "tags": " ".join(_string_list(node.get("tags"))).lower(),
        "generated_tags": " ".join(_string_list(node.get("generated_tags"))).lower(),
        "aliases": " ".join(_string_list(node.get("aliases"))).lower(),
        "headings": " ".join(str(item.get("text") or item.get("heading") or "") for item in node.get("headings", []) if isinstance(item, dict)).lower(),
        "category": str(node.get("category") or "").lower(),
        "note_type": str(node.get("note_type") or "").lower(),
        "summary": str(node.get("generated_summary") or "").lower(),
    }
    score = 0
    reasons: list[str] = []
    for term in query_terms:
        if term in haystacks["title"]:
            score += 80
            reasons.append(f"title_match:{term}")
        if term in haystacks["aliases"]:
            score += 70
            reasons.append(f"alias_match:{term}")
        if term in haystacks["tags"]:
            score += 55
            reasons.append(f"tag_match:{term}")
        if term in haystacks["generated_tags"]:
            score += 50
            reasons.append(f"generated_tag_match:{term}")
        if term in haystacks["folder"]:
            score += 40
            reasons.append(f"folder_match:{term}")
        if term in haystacks["path"]:
            score += 30
            reasons.append(f"path_match:{term}")
        if term in haystacks["headings"]:
            score += 45
            reasons.append(f"heading_match:{term}")
        if term in haystacks["category"]:
            score += 35
            reasons.append(f"category_match:{term}")
        if term in haystacks["note_type"]:
            score += 30
            reasons.append(f"note_type_match:{term}")
        if term in haystacks["summary"]:
            score += 25
            reasons.append(f"summary_match:{term}")
    for term in sorted(expanded_terms - set(query_terms)):
        if term in " ".join(haystacks.values()):
            score += 18
            reasons.append(f"synonym_match:{term}")
    source_type = str(node.get("source_type") or "vault_note")
    if source_type == "workspace_syllabus":
        score += 35
        reasons.append("syllabus_priority")
    elif source_type == "workspace_reference":
        score += 25
        reasons.append("reference_priority")
    if source_type.startswith("workspace_"):
        reasons.append("workspace_doc_priority")
    if bool(node.get("pinned")):
        score += 20
        reasons.append("pinned_context")
    folder = haystacks["folder"]
    if "_active" in folder or "/state" in folder:
        score += 10
    if "archive" in folder or "old" in folder:
        score -= 15
    return score, list(dict.fromkeys(reasons))[:8]


def _node_byte_count(node: dict[str, Any]) -> int | None:
    value = node.get("bytes")
    return value if isinstance(value, int) else None


def _estimate_tokens(byte_count: int | None) -> int | None:
    if byte_count is None:
        return None
    return max(1, int(byte_count / 4))
