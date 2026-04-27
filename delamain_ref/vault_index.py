from __future__ import annotations

import fnmatch
import hashlib
import json
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from .ingest import ensure_bundle
from .manifest import load_manifest
from .paths import RuntimePaths, ensure_base_layout
from .util import (
    SUPPORTED_INGEST_EXTENSIONS,
    atomic_write_json,
    atomic_write_text,
    sha256_file,
    slugify_bundle_id,
    to_rel_posix,
    utc_now_iso,
)

WIKILINK_RE = re.compile(r"!?(\[\[([^\]]+)\]\])")
MARKDOWN_LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)
INLINE_TAG_RE = re.compile(r"(?<!\w)#([A-Za-z0-9][A-Za-z0-9_/-]*)")
FRONTMATTER_SCAN_LIMIT_BYTES = 64 * 1024
DEFAULT_SKIP_GLOBS = [
    ".obsidian/**",
    ".stversions/**",
    ".stfolder/**",
    ".trash/**",
    ".git/**",
    "**/*.sync-conflict-*",
    "**/*.tmp",
    "**/*.temp",
    "**/*.bak",
    "**/*.base",
    "**/*.orig",
    "**/*.rej",
    "**/.DS_Store",
    "**/keys/**",
    "**/secret*/**",
    "**/secrets/**",
    "**/token*/**",
    "**/*key*.md",
    "**/*oauth*.md",
    "**/*credential*.md",
    "**/*password*.md",
    "**/*secret*.md",
    "**/*token*.md",
]


@dataclass
class NoteRecord:
    id: str
    path: str
    stem: str
    title: str
    aliases: list[str]
    tags: list[str]
    properties: dict[str, Any]
    headings: list[dict[str, Any]]
    outgoing: list[str]
    embeds: list[str]
    markdown_links: list[str]
    size_bytes: int
    mtime: str
    sha256: str
    source_type: str
    source_root: str
    category: str | None = None
    bundle_id: str | None = None
    document_md: str | None = None
    source_path: str | None = None
    converter: str | None = None
    status: str | None = None
    placement: str | None = None
    pinned: bool = False
    warnings: list[str] | None = None
    sensitivity: str = "normal"


def build_vault_index(paths: RuntimePaths, *, auto_ingest: bool = False) -> dict:
    ensure_base_layout(paths)
    ingest_result = _auto_ingest_workspace_docs(paths) if auto_ingest else _empty_ingest_result()
    policy = _load_policy(paths)
    vault_notes, skipped_paths, suppressed_targets = _collect_vault_notes(paths, policy)
    workspace_notes, workspace_warnings = _collect_workspace_bundles(paths)
    notes = [*vault_notes, *workspace_notes]
    lookup = _build_lookup(notes)
    backlinks: dict[str, list[str]] = defaultdict(list)
    dangling: dict[str, list[str]] = defaultdict(list)
    edges: list[dict[str, Any]] = []
    tags_index: dict[str, set[str]] = defaultdict(set)
    prop_index: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    headings_index: list[dict[str, Any]] = []

    for note in notes:
        for tag in note.tags:
            tags_index[tag].add(note.path)
        for key, value in note.properties.items():
            normalized = _stringify_property(value)
            prop_index[key][normalized].add(note.path)
        for heading in note.headings:
            headings_index.append(
                {
                    "file": note.path,
                    "source_id": note.id,
                    "heading": heading["text"],
                    "level": heading["level"],
                    "anchor": _slug_anchor(heading["text"]),
                }
            )

        for target in note.outgoing:
            resolved = _resolve_target(target, lookup)
            if resolved:
                edges.append(
                    {
                        "source": note.id,
                        "target": resolved["id"],
                        "kind": "wikilink",
                        "raw_target": target,
                    }
                )
                backlinks[resolved["path"]].append(note.path)
            elif not _is_suppressed_target(target, suppressed_targets):
                edges.append(
                    {
                        "source": note.id,
                        "target": target,
                        "kind": "wikilink",
                        "raw_target": target,
                    }
                )
                dangling[target].append(note.path)
        for target in note.embeds:
            resolved = _resolve_target(target, lookup)
            if resolved:
                edges.append(
                    {
                        "source": note.id,
                        "target": resolved["id"],
                        "kind": "embed",
                        "raw_target": target,
                    }
                )
                backlinks[resolved["path"]].append(note.path)
            elif not _is_suppressed_target(target, suppressed_targets):
                edges.append(
                    {
                        "source": note.id,
                        "target": target,
                        "kind": "embed",
                        "raw_target": target,
                    }
                )
                dangling[target].append(note.path)
        for target in note.markdown_links:
            resolved = _resolve_markdown_target(note.path, target, lookup)
            if resolved:
                edges.append(
                    {
                        "source": note.id,
                        "target": resolved["id"],
                        "kind": "markdown_link",
                        "raw_target": target,
                    }
                )
                backlinks[resolved["path"]].append(note.path)
            elif _is_internal_markdown_target(target) and not _is_suppressed_markdown_target(
                note.path,
                target,
                suppressed_targets,
            ):
                edges.append(
                    {
                        "source": note.id,
                        "target": target,
                        "kind": "markdown_link",
                        "raw_target": target,
                    }
                )
                dangling[target].append(note.path)

    for values in backlinks.values():
        values.sort()
    for values in dangling.values():
        values.sort()

    nodes = [
        _node_payload(note, backlinks, dangling, suppressed_targets)
        for note in sorted(notes, key=lambda item: item.path.lower())
    ]
    root_notes = sorted(
        [
            note.path
            for note in notes
            if note.source_type == "vault_note" and len(Path(note.path).parts) == 1
        ],
        key=str.lower,
    )
    recent = sorted(notes, key=lambda item: item.mtime, reverse=True)[:30]
    skip_reasons: dict[str, int] = defaultdict(int)
    for item in skipped_paths:
        skip_reasons[item["reason"]] += 1
    manifest = {
        "schema_version": 2,
        "generated_at": utc_now_iso(),
        "source_root": paths.vault_root.as_posix(),
        "workspace_root": paths.workspace_root.as_posix(),
        "file_count": len(notes),
        "indexed_count": len(notes),
        "vault_note_count": len(vault_notes),
        "workspace_bundle_count": len(workspace_notes),
        "skipped_count": len(skipped_paths),
        "skipped_paths": skipped_paths,
        "skip_reasons": dict(sorted(skip_reasons.items())),
        "policy_hash": policy["hash"],
        "policy_sources": policy["sources"],
        "edge_count": len(edges),
        "dangling_link_count": len(dangling),
        "warnings": sorted(set([*workspace_warnings, *ingest_result["warnings"]])),
        "auto_ingest": ingest_result,
        "files": [
            {
                "id": note.id,
                "path": note.path,
                "source_type": note.source_type,
                "sha256": note.sha256,
                "mtime": note.mtime,
                "size_bytes": note.size_bytes,
                "status": note.status,
            }
            for note in sorted(notes, key=lambda item: item.path.lower())
        ],
    }

    output_root = paths.vault_index_root
    focus_root = output_root / "focus"
    focus_root.mkdir(parents=True, exist_ok=True)
    output_root.mkdir(parents=True, exist_ok=True)

    atomic_write_json(output_root / "_manifest.json", manifest)
    atomic_write_json(output_root / "graph.json", {"nodes": nodes, "edges": edges})
    atomic_write_json(output_root / "backlinks.json", dict(sorted(backlinks.items())))
    atomic_write_json(
        output_root / "tags.json",
        {
            "tags": [
                {"tag": key, "count": len(value), "files": sorted(value)}
                for key, value in sorted(tags_index.items())
            ]
        },
    )
    atomic_write_json(
        output_root / "properties.json",
        {
            "properties": {
                prop: {
                    val: sorted(paths_set) for val, paths_set in sorted(value_map.items())
                }
                for prop, value_map in sorted(prop_index.items())
            }
        },
    )
    atomic_write_json(
        output_root / "headings.json",
        {"headings": sorted(headings_index, key=lambda x: (x["file"], x["level"], x["heading"]))},
    )
    atomic_write_text(output_root / "root-notes.md", _render_root_notes(root_notes))
    atomic_write_text(output_root / "dangling-links.md", _render_dangling(dangling))
    atomic_write_text(output_root / "_index.md", _render_index_summary(manifest, root_notes, dangling, recent))
    atomic_write_text(focus_root / "timeline.md", _render_focus_timeline(notes))
    atomic_write_text(focus_root / "journals.md", _render_focus_journals(notes))
    atomic_write_text(focus_root / "ambitions.md", _render_focus_ambitions(notes))

    changed = [
        "vault-index/_manifest.json",
        "vault-index/graph.json",
        "vault-index/backlinks.json",
        "vault-index/tags.json",
        "vault-index/properties.json",
        "vault-index/headings.json",
        "vault-index/root-notes.md",
        "vault-index/dangling-links.md",
        "vault-index/_index.md",
        "vault-index/focus/timeline.md",
        "vault-index/focus/journals.md",
        "vault-index/focus/ambitions.md",
    ]
    return {
        "ok": True,
        "command": "build",
        "status": "ok",
        "warnings": manifest["warnings"],
        "errors": [],
        "changed_paths": sorted(set([*changed, *ingest_result["changed_paths"]])),
        "summary": {
            "file_count": len(notes),
            "vault_note_count": len(vault_notes),
            "workspace_bundle_count": len(workspace_notes),
            "edge_count": len(edges),
            "dangling_link_count": len(dangling),
            "root_note_count": len(root_notes),
            "skipped_count": len(skipped_paths),
            "auto_ingest": ingest_result,
        },
        "message": "Unified vault index build complete.",
    }


def vault_index_status(paths: RuntimePaths) -> dict:
    manifest_path = paths.vault_index_root / "_manifest.json"
    if not manifest_path.exists():
        return {
            "ok": False,
            "command": "status",
            "status": "error",
            "warnings": [],
            "errors": ["Vault index is missing. Run `delamain-vault-index build` first."],
            "changed_paths": [],
            "message": "Vault index not built.",
        }
    payload = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    return {
        "ok": True,
        "command": "status",
        "status": "ok",
        "warnings": payload.get("warnings", []),
        "errors": [],
        "changed_paths": [],
        "summary": {
            "schema_version": payload.get("schema_version", 1),
            "generated_at": payload.get("generated_at"),
            "file_count": payload.get("file_count", 0),
            "vault_note_count": payload.get("vault_note_count", payload.get("file_count", 0)),
            "workspace_bundle_count": payload.get("workspace_bundle_count", 0),
            "skipped_count": payload.get("skipped_count", len(payload.get("skipped_paths", []))),
            "source_root": payload.get("source_root"),
            "workspace_root": payload.get("workspace_root"),
            "policy_hash": payload.get("policy_hash"),
        },
        "message": "Vault index status loaded.",
    }


def vault_index_query(paths: RuntimePaths, term: str) -> dict:
    term_lower = term.lower()
    graph_path = paths.vault_index_root / "graph.json"
    tags_path = paths.vault_index_root / "tags.json"
    headings_path = paths.vault_index_root / "headings.json"
    if not graph_path.exists():
        return _missing_build("query")
    graph = yaml.safe_load(graph_path.read_text(encoding="utf-8")) or {}
    tags = yaml.safe_load(tags_path.read_text(encoding="utf-8")) if tags_path.exists() else {"tags": []}
    headings = (
        yaml.safe_load(headings_path.read_text(encoding="utf-8"))
        if headings_path.exists()
        else {"headings": []}
    )
    matches = []
    for node in graph.get("nodes", []):
        haystack = " ".join(
            [
                node.get("path", ""),
                node.get("title", ""),
                node.get("source_type", ""),
                node.get("category", "") or "",
                " ".join(node.get("aliases", [])),
                " ".join(node.get("tags", [])),
            ]
        ).lower()
        if term_lower in haystack:
            matches.append({"kind": "note", "value": node.get("path"), "source_type": node.get("source_type")})
    for tag_row in tags.get("tags", []):
        if term_lower in str(tag_row.get("tag", "")).lower():
            matches.append({"kind": "tag", "value": tag_row.get("tag"), "count": tag_row.get("count")})
    for heading in headings.get("headings", []):
        if term_lower in str(heading.get("heading", "")).lower():
            matches.append({"kind": "heading", "value": heading})
    return {
        "ok": True,
        "command": "query",
        "status": "ok",
        "warnings": [],
        "errors": [],
        "changed_paths": [],
        "matches": matches,
        "message": f"Found {len(matches)} vault index match(es).",
    }


def vault_index_backlinks(paths: RuntimePaths, note_term: str) -> dict:
    data = _load_json_file(paths.vault_index_root / "backlinks.json")
    if data is None:
        return _missing_build("backlinks")
    candidates = [key for key in data.keys() if note_term.lower() in key.lower()]
    if not candidates:
        return {
            "ok": True,
            "command": "backlinks",
            "status": "ok",
            "warnings": [f"No backlink target matched `{note_term}`."],
            "errors": [],
            "changed_paths": [],
            "matches": {},
            "message": "No backlinks matched.",
        }
    return {
        "ok": True,
        "command": "backlinks",
        "status": "ok",
        "warnings": [],
        "errors": [],
        "changed_paths": [],
        "matches": {key: data[key] for key in sorted(candidates)},
        "message": f"Returned backlinks for {len(candidates)} target note(s).",
    }


def vault_index_dangling(paths: RuntimePaths) -> dict:
    dangling_path = paths.vault_index_root / "dangling-links.md"
    if not dangling_path.exists():
        return _missing_build("dangling")
    content = dangling_path.read_text(encoding="utf-8")
    entries = [line[2:] for line in content.splitlines() if line.startswith("- ")]
    return {
        "ok": True,
        "command": "dangling",
        "status": "ok",
        "warnings": [],
        "errors": [],
        "changed_paths": [],
        "entries": entries,
        "message": f"Found {len(entries)} dangling link target(s).",
    }


def vault_index_root_notes(paths: RuntimePaths) -> dict:
    root_path = paths.vault_index_root / "root-notes.md"
    if not root_path.exists():
        return _missing_build("root-notes")
    lines = [line[2:] for line in root_path.read_text(encoding="utf-8").splitlines() if line.startswith("- ")]
    return {
        "ok": True,
        "command": "root-notes",
        "status": "ok",
        "warnings": [],
        "errors": [],
        "changed_paths": [],
        "entries": lines,
        "message": f"Found {len(lines)} root-level note(s).",
    }


def vault_index_heartbeat(paths: RuntimePaths) -> dict:
    started = datetime.now().astimezone()
    result = build_vault_index(paths, auto_ingest=True)
    finished = datetime.now().astimezone()
    heartbeat = {
        "generated_at": utc_now_iso(),
        "last_run_started_at": started.isoformat(),
        "last_run_finished_at": finished.isoformat(),
        "duration_ms": int((finished - started).total_seconds() * 1000),
        "status": result["status"],
        "ok": result["ok"],
        "changed_paths": result["changed_paths"],
        "warnings": result["warnings"],
        "errors": result["errors"],
        "summary": result["summary"],
    }
    atomic_write_json(paths.vault_index_root / "_heartbeat.json", heartbeat)
    return {
        **result,
        "command": "heartbeat",
        "heartbeat": heartbeat,
        "message": "Vault index heartbeat complete.",
    }


def init_vault_folder(paths: RuntimePaths, *, kind: str, name: str) -> dict:
    ensure_base_layout(paths)
    normalized_kind = kind.strip().lower()
    if normalized_kind not in {"project", "course", "reference"}:
        return _error_result("init-folder", [f"Unsupported folder kind: {kind}"])
    title = " ".join(name.strip().split()) or f"New {normalized_kind.title()}"
    slug = slugify_bundle_id(title)
    changed: list[str] = []

    if normalized_kind == "project":
        vault_dir = _unique_dir(paths.vault_root / "Projects" / title)
        workspace_dir = _unique_dir(paths.reference_root / slug)
        tag = "project/active"
    elif normalized_kind == "course":
        vault_dir = _unique_dir(paths.vault_root / "Notes" / "School" / title)
        workspace_dir = _unique_dir(paths.syllabi_root / slug)
        tag = "course/active"
    else:
        vault_dir = _unique_dir(paths.vault_root / "Reference" / title)
        workspace_dir = _unique_dir(paths.reference_root / slug)
        tag = "reference"

    for directory in [vault_dir, vault_dir / "archive", workspace_dir / "original", workspace_dir / "figures"]:
        directory.mkdir(parents=True, exist_ok=True)
        changed.append(_rel_any(paths, directory))
    files = {
        vault_dir / "INDEX.md": _folder_note(title, tag, "Index"),
        vault_dir / "state.md": _folder_note(title, tag, "State"),
        vault_dir / "decisions.md": _folder_note(title, tag, "Decisions"),
        vault_dir / "tasks.md": _folder_note(title, tag, "Tasks"),
        workspace_dir / "README.md": f"# {title}\n\nDrop source documents into `original/` or the category root, then run ingestion.\n",
    }
    for path, content in files.items():
        if not path.exists():
            atomic_write_text(path, content)
            changed.append(_rel_any(paths, path))

    build_result = build_vault_index(paths, auto_ingest=False)
    return {
        "ok": True,
        "command": "init-folder",
        "status": "ok",
        "warnings": build_result["warnings"],
        "errors": [],
        "changed_paths": sorted(set([*changed, *build_result["changed_paths"]])),
        "summary": {
            "kind": normalized_kind,
            "name": title,
            "vault_dir": _rel_any(paths, vault_dir),
            "workspace_dir": _rel_any(paths, workspace_dir),
            **build_result["summary"],
        },
        "message": f"Initialized {normalized_kind} folder `{title}`.",
    }


def _collect_vault_notes(
    paths: RuntimePaths,
    policy: dict[str, Any],
) -> tuple[list[NoteRecord], list[dict[str, Any]], set[str]]:
    notes: list[NoteRecord] = []
    skipped: list[dict[str, Any]] = []
    suppressed_targets: set[str] = set()
    for file_path in sorted(paths.vault_root.rglob("*.md"), key=lambda p: p.as_posix().lower()):
        rel = to_rel_posix(paths.vault_root, file_path)
        reason = _skip_reason(rel, policy["patterns"])
        if reason:
            suppressed_targets.update(_suppression_keys_for_path(rel))
            skipped.append({"path": rel, "reason": reason})
            continue
        preflight_frontmatter = _read_frontmatter_prescan(file_path)
        if _frontmatter_scan_unclosed(preflight_frontmatter):
            suppressed_targets.update(_suppression_keys_for_path(rel))
            skipped.append({"path": None, "reason": "frontmatter:unterminated"})
            continue
        sensitivity = _frontmatter_sensitivity(preflight_frontmatter)
        if sensitivity in {"private", "sensitive"}:
            suppressed_targets.update(_suppression_keys_for_path(rel))
            suppressed_targets.update(_suppression_keys_for_frontmatter(preflight_frontmatter))
            skipped.append(
                {
                    "path": None,
                    "reason": f"frontmatter:{sensitivity}",
                }
            )
            continue
        try:
            text = file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            skipped.append({"path": rel, "reason": "decode_error"})
            continue
        frontmatter, body = _split_frontmatter(text)
        tags = _parse_tags(frontmatter, body)
        aliases = _parse_aliases(frontmatter)
        headings = _parse_headings(body)
        outgoing, embeds = _parse_wikilinks(body)
        markdown_links = _parse_markdown_links(body)
        title = str(frontmatter.get("title") or (headings[0]["text"] if headings else file_path.stem))
        archive_state = "archive" if "archive" in rel.lower().split("/") else "active"
        notes.append(
            NoteRecord(
                id=rel,
                path=rel,
                stem=file_path.stem,
                title=title,
                aliases=aliases,
                tags=tags,
                properties=frontmatter,
                headings=headings,
                outgoing=outgoing,
                embeds=embeds,
                markdown_links=markdown_links,
                size_bytes=file_path.stat().st_size,
                mtime=_iso_mtime(file_path),
                sha256=sha256_file(file_path),
                source_type="vault_note",
                source_root=paths.vault_root.as_posix(),
                status="fresh",
                placement=archive_state,
                warnings=[],
                sensitivity=sensitivity,
            )
        )
    return notes, skipped, suppressed_targets


def _collect_workspace_bundles(paths: RuntimePaths) -> tuple[list[NoteRecord], list[str]]:
    notes: list[NoteRecord] = []
    warnings: list[str] = []
    for category, source_type in [("syllabi", "workspace_syllabus"), ("reference", "workspace_reference")]:
        manifest = load_manifest(paths, category)
        for bundle in manifest.bundles:
            document_path = paths.workspace_root / bundle.document_md
            metadata_path = paths.workspace_root / bundle.bundle_path / "metadata.json"
            extraction_path = paths.workspace_root / bundle.bundle_path / "extraction.json"
            metadata = _load_json_file(metadata_path) or {}
            extraction = _load_json_file(extraction_path) or {}
            text = ""
            headings: list[dict[str, Any]] = []
            tags: list[str] = [category, source_type.replace("workspace_", "")]
            outgoing: list[str] = []
            embeds: list[str] = []
            markdown_links: list[str] = []
            size_bytes = 0
            sha = bundle.source_sha256
            mtime = bundle.source_mtime
            if document_path.exists():
                text = document_path.read_text(encoding="utf-8", errors="replace")
                headings = _parse_headings(text)
                tags = sorted(set([*tags, *_parse_tags({}, text)]))
                outgoing, embeds = _parse_wikilinks(text)
                markdown_links = _parse_markdown_links(text)
                size_bytes = document_path.stat().st_size
                sha = sha256_file(document_path)
                mtime = _iso_mtime(document_path)
            else:
                warnings.append(f"Workspace bundle `{bundle.id}` is missing document.md")
            title = bundle.title or (headings[0]["text"] if headings else bundle.id)
            notes.append(
                NoteRecord(
                    id=f"{category}:{bundle.id}",
                    path=bundle.document_md,
                    stem=Path(bundle.document_md).stem,
                    title=title,
                    aliases=[bundle.id],
                    tags=tags,
                    properties={
                        "category": category,
                        "status": bundle.status,
                        "placement": bundle.placement,
                        "pinned": bundle.pinned,
                        "metadata_status": (metadata.get("conversion") or {}).get("status"),
                        "extraction_kind": (extraction.get("kind") if isinstance(extraction, dict) else None),
                    },
                    headings=headings,
                    outgoing=outgoing,
                    embeds=embeds,
                    markdown_links=markdown_links,
                    size_bytes=size_bytes,
                    mtime=mtime,
                    sha256=sha,
                    source_type=source_type,
                    source_root=paths.workspace_root.as_posix(),
                    category=category,
                    bundle_id=bundle.id,
                    document_md=bundle.document_md,
                    source_path=bundle.source_path,
                    converter=bundle.converter,
                    status=bundle.status,
                    placement=bundle.placement,
                    pinned=bundle.pinned,
                    warnings=bundle.warnings,
                )
            )
    return notes, warnings


def _auto_ingest_workspace_docs(paths: RuntimePaths) -> dict[str, Any]:
    changed_paths: list[str] = []
    warnings: list[str] = []
    errors: list[str] = []
    ingested: list[str] = []
    for category in ["syllabi", "reference"]:
        root = paths.category_root(category)
        root.mkdir(parents=True, exist_ok=True)
        for source in sorted(root.iterdir(), key=lambda p: p.name.lower()):
            if not source.is_file() or source.suffix.lower() not in SUPPORTED_INGEST_EXTENSIONS:
                continue
            if "sync-conflict" in source.name.lower():
                warnings.append(f"Skipped conflicted document: {source.name}")
                continue
            try:
                result = ensure_bundle(paths, str(source), category=category, dry_run=False, force=False)
            except Exception as exc:
                errors.append(f"{source.name}: {exc}")
                continue
            changed_paths.extend(result.get("changed_paths", []))
            warnings.extend(result.get("warnings", []))
            if result.get("ok"):
                ingested.append(source.name)
            else:
                errors.extend(result.get("errors", []))
    return {
        "ingested": ingested,
        "changed_paths": sorted(set(changed_paths)),
        "warnings": sorted(set(warnings)),
        "errors": sorted(set(errors)),
    }


def _empty_ingest_result() -> dict[str, Any]:
    return {"ingested": [], "changed_paths": [], "warnings": [], "errors": []}


def _node_payload(
    note: NoteRecord,
    backlinks: dict[str, list[str]],
    dangling: dict[str, list[str]],
    suppressed_targets: set[str],
) -> dict[str, Any]:
    folder = str(Path(note.path).parent).replace("\\", "/")
    outgoing = [target for target in note.outgoing if not _is_suppressed_target(target, suppressed_targets)]
    embeds = [target for target in note.embeds if not _is_suppressed_target(target, suppressed_targets)]
    markdown_links = [
        target
        for target in note.markdown_links
        if not _is_suppressed_markdown_target(note.path, target, suppressed_targets)
    ]
    outgoing_dangling = sum(
        1 for target in [*outgoing, *embeds, *markdown_links] if target in dangling
    )
    return {
        "id": note.id,
        "path": note.path,
        "title": note.title,
        "aliases": note.aliases,
        "folder": folder,
        "folder_parts": [] if folder == "." else folder.split("/"),
        "tags": note.tags,
        "properties": sorted(note.properties.keys()),
        "headings": note.headings,
        "outgoing_links": sorted(outgoing),
        "markdown_links": sorted(markdown_links),
        "embeds": sorted(embeds),
        "incoming_link_count": len(backlinks.get(note.path, [])),
        "dangling_link_count": outgoing_dangling,
        "size_bytes": note.size_bytes,
        "mtime": note.mtime,
        "sha256": note.sha256,
        "source_type": note.source_type,
        "source_root": note.source_root,
        "category": note.category,
        "bundle_id": note.bundle_id,
        "document_md": note.document_md,
        "source_path": note.source_path,
        "converter": note.converter,
        "status": note.status,
        "placement": note.placement,
        "pinned": note.pinned,
        "warnings": note.warnings or [],
        "archive_state": (
            "archive"
            if note.placement in {"archive", "long-term"} or "archive" in folder.lower()
            else "active"
        ),
        "policy_state": "allowed",
        "sensitivity": note.sensitivity,
    }


def _build_lookup(notes: list[NoteRecord]) -> dict[str, dict[str, str]]:
    candidates: dict[str, list[NoteRecord]] = defaultdict(list)
    for note in notes:
        rel_no_ext = Path(note.path).with_suffix("").as_posix().lower()
        keys = {
            note.id.lower(),
            note.path.lower(),
            rel_no_ext,
            Path(note.path).stem.lower(),
        }
        parts = rel_no_ext.split("/")
        for idx in range(1, len(parts)):
            keys.add("/".join(parts[idx:]))
        for alias in note.aliases:
            keys.add(alias.lower())
        for key in keys:
            if key:
                candidates[key].append(note)
    lookup: dict[str, dict[str, str]] = {}
    for key, values in candidates.items():
        if len(values) == 1:
            note = values[0]
            lookup[key] = {"id": note.id, "path": note.path}
    return lookup


def _resolve_target(target: str, lookup: dict[str, dict[str, str]]) -> dict[str, str] | None:
    clean = target.split("#", 1)[0].strip().replace("\\", "/")
    clean = clean[:-3] if clean.lower().endswith(".md") else clean
    return lookup.get(clean.lower())


def _resolve_markdown_target(
    source_path: str,
    target: str,
    lookup: dict[str, dict[str, str]],
) -> dict[str, str] | None:
    if not _is_internal_markdown_target(target):
        return None
    base = Path(source_path).parent
    raw = target.split("#", 1)[0]
    candidate = (base / raw).as_posix()
    normalized = Path(candidate).with_suffix("").as_posix().lower()
    return lookup.get(normalized) or lookup.get(Path(raw).stem.lower())


def _is_internal_markdown_target(target: str) -> bool:
    lower = target.lower()
    return not (
        lower.startswith("http://")
        or lower.startswith("https://")
        or lower.startswith("mailto:")
        or lower.startswith("#")
    )


def _read_frontmatter_prescan(
    path: Path,
    *,
    limit_bytes: int = FRONTMATTER_SCAN_LIMIT_BYTES,
) -> dict[str, Any]:
    try:
        with path.open("rb") as handle:
            data = handle.read(limit_bytes)
    except OSError:
        return {}
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    if not (data.startswith(b"---\n") or data.startswith(b"---\r\n")):
        return {}
    lines = data.splitlines(keepends=True)
    for index, line in enumerate(lines[1:], start=1):
        stripped = line.strip()
        if stripped in {b"---", b"..."}:
            raw = b"".join(lines[1:index])
            try:
                parsed = yaml.safe_load(raw.decode("utf-8", errors="replace")) or {}
            except Exception:
                return {}
            return parsed if isinstance(parsed, dict) else {}
    return {"__delamain_frontmatter_unclosed__": True}


def _frontmatter_scan_unclosed(frontmatter: dict[str, Any]) -> bool:
    return bool(frontmatter.get("__delamain_frontmatter_unclosed__"))


def _frontmatter_sensitivity(frontmatter: dict[str, Any]) -> str:
    value = str(frontmatter.get("sensitivity") or "").strip().lower()
    if value in {"private", "sensitive"}:
        return value
    return "normal"


def _suppression_keys_for_path(rel_path: str) -> set[str]:
    normalized = rel_path.replace("\\", "/").strip()
    without_ext = Path(normalized).with_suffix("").as_posix()
    parts = without_ext.split("/")
    keys = {
        normalized,
        without_ext,
        Path(normalized).stem,
    }
    for idx in range(1, len(parts)):
        keys.add("/".join(parts[idx:]))
    return {_normalize_link_key(key) for key in keys if key}


def _suppression_keys_for_frontmatter(frontmatter: dict[str, Any]) -> set[str]:
    keys = set(_parse_aliases(frontmatter))
    title = frontmatter.get("title")
    if title is not None:
        keys.add(str(title))
    return {_normalize_link_key(key) for key in keys if str(key).strip()}


def _is_suppressed_target(target: str, suppressed_targets: set[str]) -> bool:
    clean = target.split("#", 1)[0].strip().replace("\\", "/")
    if clean.lower().endswith(".md"):
        clean = clean[:-3]
    return _normalize_link_key(clean) in suppressed_targets


def _is_suppressed_markdown_target(
    source_path: str,
    target: str,
    suppressed_targets: set[str],
) -> bool:
    raw = target.split("#", 1)[0].strip()
    base = Path(source_path).parent
    candidate = (base / raw).as_posix()
    return (
        _normalize_link_key(Path(candidate).with_suffix("").as_posix()) in suppressed_targets
        or _normalize_link_key(Path(raw).stem) in suppressed_targets
    )


def _normalize_link_key(value: str) -> str:
    clean = value.strip().replace("\\", "/")
    clean = clean[:-3] if clean.lower().endswith(".md") else clean
    return clean.lower()


def _split_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    if not content.startswith("---\n"):
        return {}, content
    marker = content.find("\n---\n", 4)
    if marker == -1:
        return {}, content
    frontmatter_raw = content[4:marker]
    body = content[marker + 5 :]
    try:
        parsed = yaml.safe_load(frontmatter_raw) or {}
    except Exception:
        parsed = {}
    if not isinstance(parsed, dict):
        parsed = {}
    return parsed, body


def _parse_aliases(frontmatter: dict[str, Any]) -> list[str]:
    aliases = frontmatter.get("aliases", [])
    if isinstance(aliases, str):
        return [aliases]
    if isinstance(aliases, list):
        return [str(item) for item in aliases if str(item).strip()]
    return []


def _parse_tags(frontmatter: dict[str, Any], body: str) -> list[str]:
    tags: set[str] = set()
    fm_tags = frontmatter.get("tags", [])
    if isinstance(fm_tags, str):
        tags.add(fm_tags.lstrip("#"))
    elif isinstance(fm_tags, list):
        for item in fm_tags:
            tags.add(str(item).lstrip("#"))
    for match in INLINE_TAG_RE.findall(body):
        if match:
            tags.add(match.lstrip("#"))
    return sorted(tags)


def _parse_headings(body: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for hashes, heading_text in HEADING_RE.findall(body):
        rows.append({"level": len(hashes), "text": heading_text.strip()})
    return rows


def _parse_wikilinks(body: str) -> tuple[list[str], list[str]]:
    outgoing: list[str] = []
    embeds: list[str] = []
    for full, raw in WIKILINK_RE.findall(body):
        target = raw.split("|", 1)[0].strip()
        if not target:
            continue
        if full.startswith("!"):
            embeds.append(target)
        else:
            outgoing.append(target)
    return sorted(set(outgoing)), sorted(set(embeds))


def _parse_markdown_links(body: str) -> list[str]:
    return sorted(set(link.strip() for link in MARKDOWN_LINK_RE.findall(body) if link.strip()))


def _load_policy(paths: RuntimePaths) -> dict[str, Any]:
    sources = [
        paths.vault_root / "vault_policy.md",
        paths.vault_root / ".modelignore",
        paths.vault_root / ".delamainignore",
    ]
    patterns = list(DEFAULT_SKIP_GLOBS)
    source_payloads: list[dict[str, str]] = []
    digest = hashlib.sha256()
    for source in sources:
        if not source.exists():
            continue
        text = source.read_text(encoding="utf-8")
        digest.update(source.as_posix().encode("utf-8"))
        digest.update(text.encode("utf-8"))
        source_payloads.append({"path": source.as_posix(), "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()})
        patterns.extend(_parse_ignore_patterns(text, markdown=source.name == "vault_policy.md"))
    return {
        "patterns": list(dict.fromkeys(patterns)),
        "sources": source_payloads,
        "hash": f"sha256:{digest.hexdigest()}",
    }


def _parse_ignore_patterns(text: str, *, markdown: bool = True) -> list[str]:
    patterns: list[str] = []
    in_fence = False
    fence_is_ignore = False
    in_ignore_section = not markdown
    for line in text.splitlines():
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
        if markdown and stripped.startswith("## "):
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
        if "#" in stripped and not in_fence:
            stripped = stripped.split("#", 1)[0].strip()
        stripped = stripped.strip("`")
        if stripped and not markdown:
            patterns.append(stripped)
    return patterns


def _looks_like_ignore_pattern(value: str) -> bool:
    return (
        "*" in value
        or "/" in value
        or "\\" in value
        or value.startswith(".")
        or value.startswith("*.")
    )


def _skip_reason(rel_path: str, patterns: list[str]) -> str | None:
    normalized = rel_path.replace("\\", "/")
    lowered = normalized.lower()
    for pattern in patterns:
        clean = pattern.strip().lstrip("/")
        if not clean:
            continue
        if fnmatch.fnmatch(normalized, clean) or fnmatch.fnmatch(lowered, clean.lower()) or fnmatch.fnmatch(Path(normalized).name, clean):
            return f"glob:{pattern}"
    return None


def _render_root_notes(root_notes: list[str]) -> str:
    lines = ["# Root Notes", ""]
    if not root_notes:
        lines.append("_No root notes found._")
        return "\n".join(lines).rstrip() + "\n"
    for note in root_notes:
        lines.append(f"- {note}")
    return "\n".join(lines).rstrip() + "\n"


def _render_dangling(dangling: dict[str, list[str]]) -> str:
    lines = ["# Dangling Links", ""]
    if not dangling:
        lines.append("_No dangling links found._")
        return "\n".join(lines).rstrip() + "\n"
    for target in sorted(dangling.keys(), key=str.lower):
        sources = ", ".join(dangling[target])
        lines.append(f"- {target}: {sources}")
    return "\n".join(lines).rstrip() + "\n"


def _render_index_summary(manifest: dict[str, Any], root_notes: list[str], dangling: dict[str, list[str]], recent: list[NoteRecord]) -> str:
    lines = [
        "# Unified Vault Index",
        "",
        f"Generated at: `{manifest['generated_at']}`",
        f"Vault root: `{manifest['source_root']}`",
        f"Workspace root: `{manifest['workspace_root']}`",
        f"Indexed count: `{manifest['indexed_count']}`",
        f"Vault notes: `{manifest['vault_note_count']}`",
        f"Workspace bundles: `{manifest['workspace_bundle_count']}`",
        f"Skipped paths: `{manifest['skipped_count']}`",
        f"Dangling link targets: `{len(dangling)}`",
        "",
        "## Recently Modified",
        "",
    ]
    if not recent:
        lines.append("_No notes indexed._")
    else:
        for note in recent[:15]:
            lines.append(f"- {note.path} (`{note.source_type}`, `{note.mtime}`)")
    lines.extend(
        [
            "",
            "## Focus Files",
            "",
            "- [timeline.md](focus/timeline.md)",
            "- [journals.md](focus/journals.md)",
            "- [ambitions.md](focus/ambitions.md)",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def _render_focus_timeline(notes: list[NoteRecord]) -> str:
    lines = ["# Timeline Focus", ""]
    hits = [note.path for note in notes if "timeline" in note.path.lower()]
    if not hits:
        lines.append("_No timeline-focused notes found._")
    else:
        for path in sorted(hits):
            lines.append(f"- {path}")
    return "\n".join(lines).rstrip() + "\n"


def _render_focus_journals(notes: list[NoteRecord]) -> str:
    lines = ["# Journals Focus", ""]
    hits = [
        note.path
        for note in notes
        if any(token in note.path.lower() for token in ["journal", "week", "daily", "post_break_week"])
    ]
    if not hits:
        lines.append("_No journal-focused notes found._")
    else:
        for path in sorted(set(hits)):
            lines.append(f"- {path}")
    return "\n".join(lines).rstrip() + "\n"


def _render_focus_ambitions(notes: list[NoteRecord]) -> str:
    lines = ["# Ambitions Focus", ""]
    hits = [note.path for note in notes if any(token in note.path.lower() for token in ["ambition", "goal", "vision"])]
    if not hits:
        lines.append("_No ambition-focused notes found._")
    else:
        for path in sorted(set(hits)):
            lines.append(f"- {path}")
    return "\n".join(lines).rstrip() + "\n"


def _stringify_property(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(_stringify_property(item) for item in value)
    if isinstance(value, dict):
        return yaml.safe_dump(value, sort_keys=True).strip()
    return str(value)


def _slug_anchor(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")


def _iso_mtime(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat()


def _load_json_file(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return yaml.safe_load(path.read_text(encoding="utf-8"))


def _folder_note(title: str, tag: str, kind: str) -> str:
    return f"---\ntags: [{tag}]\naliases: [{title} {kind}]\n---\n\n# {title} {kind}\n\n"


def _unique_dir(path: Path) -> Path:
    if not path.exists():
        return path
    base = path
    index = 2
    while True:
        candidate = base.with_name(f"{base.name} {index}")
        if not candidate.exists():
            return candidate
        index += 1


def _rel_any(paths: RuntimePaths, path: Path) -> str:
    for root_name, root in [("vault", paths.vault_root), ("workspace", paths.workspace_root)]:
        try:
            return f"{root_name}:{to_rel_posix(root, path)}"
        except ValueError:
            continue
    return path.as_posix()


def _error_result(command: str, errors: list[str]) -> dict[str, Any]:
    return {
        "ok": False,
        "command": command,
        "status": "error",
        "warnings": [],
        "errors": errors,
        "changed_paths": [],
        "message": errors[0] if errors else "Command failed.",
    }


def _missing_build(command: str) -> dict[str, Any]:
    return {
        "ok": False,
        "command": command,
        "status": "error",
        "warnings": [],
        "errors": ["Vault index missing. Run `delamain-vault-index build` first."],
        "changed_paths": [],
        "message": "Vault index not built.",
    }
