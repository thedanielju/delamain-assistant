from __future__ import annotations

import shutil
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from .converters import (
    build_metadata_payload,
    convert_rich_document,
    detect_dependencies,
)
from .index_md import rebuild_category_index
from .manifest import (
    BundleRecord,
    CategoryManifest,
    get_bundle,
    index_path,
    load_manifest,
    manifest_path,
    replace_bundle,
    save_manifest,
)
from .paths import RuntimePaths, ensure_base_layout
from .util import (
    EXCLUDED_INGEST_EXTENSIONS,
    SUPPORTED_INGEST_EXTENSIONS,
    atomic_write_json,
    atomic_write_text,
    resolve_collision,
    sha256_file,
    slugify_bundle_id,
    to_rel_posix,
    utc_now_iso,
)


def ensure_category_ready(paths: RuntimePaths, category: str) -> None:
    ensure_base_layout(paths)
    root = paths.category_root(category)
    (root / "_long-term").mkdir(parents=True, exist_ok=True)
    current_manifest_path = manifest_path(paths, category)
    current_index_path = index_path(paths, category)
    manifest = load_manifest(paths, category)
    if not current_manifest_path.exists():
        save_manifest(paths, manifest)
    if not current_index_path.exists():
        rebuild_category_index(paths, manifest)


def list_category(
    paths: RuntimePaths, category: str, include_long_term: bool, include_all: bool
) -> list[dict]:
    manifest = load_manifest(paths, category)
    rows: list[dict] = []
    for bundle in manifest.bundles:
        if include_all:
            rows.append(asdict(bundle))
            continue
        if include_long_term and bundle.placement == "long-term":
            rows.append(asdict(bundle))
        elif not include_long_term and bundle.placement == "normal":
            rows.append(asdict(bundle))
    return rows


def find_bundle_by_id(
    paths: RuntimePaths, bundle_id: str, category: str | None = None
) -> tuple[str, CategoryManifest, BundleRecord] | None:
    categories = [category] if category else ["syllabi", "reference"]
    for item in categories:
        manifest = load_manifest(paths, item)
        bundle = get_bundle(manifest, bundle_id)
        if bundle:
            return item, manifest, bundle
    return None


def ensure_bundle(
    paths: RuntimePaths,
    target: str,
    *,
    category: str | None = None,
    dry_run: bool = False,
    force: bool = False,
) -> dict:
    ensure_base_layout(paths)
    target_path = Path(target)
    warnings: list[str] = []

    if target_path.exists():
        return _ensure_from_path(paths, target_path, category=category, dry_run=dry_run, force=force)

    found = find_bundle_by_id(paths, target, category=category)
    if not found:
        return _error_result("ensure", [f"Target not found as file path or bundle id: {target}"])

    cat, manifest, bundle = found
    bundle.last_accessed_at = utc_now_iso()
    if not dry_run:
        save_manifest(paths, manifest)
        rebuild_category_index(paths, manifest)
    return {
        "ok": True,
        "command": "ensure",
        "status": "ok",
        "warnings": warnings,
        "errors": [],
        "changed_paths": [],
        "bundle": asdict(bundle),
        "message": f"Bundle `{bundle.id}` is already indexed in `{cat}`.",
    }


def _ensure_from_path(
    paths: RuntimePaths,
    source_path: Path,
    *,
    category: str | None,
    dry_run: bool,
    force: bool,
) -> dict:
    resolved_source = source_path.resolve()
    extension = resolved_source.suffix.lower()
    if extension in EXCLUDED_INGEST_EXTENSIONS:
        return _error_result(
            "ensure", [f"Excluded extension `{extension}` is not ingested by design."]
        )
    if extension not in SUPPORTED_INGEST_EXTENSIONS:
        return _error_result(
            "ensure",
            [
                f"Unsupported extension `{extension}`. Supported: {', '.join(sorted(SUPPORTED_INGEST_EXTENSIONS))}."
            ],
        )

    inferred_category = category or _infer_category(paths, resolved_source)
    if not inferred_category:
        return _error_result(
            "ensure",
            [
                "Category could not be inferred. Place file inside `syllabi/` or `reference/`, or pass --category."
            ],
        )
    ensure_category_ready(paths, inferred_category)
    manifest = load_manifest(paths, inferred_category)

    bundle = _find_bundle_for_source(paths, manifest, resolved_source)
    changed_paths: list[str] = []
    warnings: list[str] = []
    now = utc_now_iso()

    if bundle is None:
        if not _is_loose_category_source(paths, inferred_category, resolved_source):
            return _error_result(
                "ensure",
                [
                    "Source path must be a loose rich file in category root or an existing bundle source.",
                    f"Received: {resolved_source}",
                ],
            )
        bundle = _build_new_bundle_record(
            paths=paths,
            manifest=manifest,
            category=inferred_category,
            source_path=resolved_source,
            now=now,
        )
        replace_bundle(manifest, bundle)

    bundle_root = paths.workspace_root / Path(bundle.bundle_path)
    original_dir = bundle_root / "original"
    source_in_bundle = paths.workspace_root / Path(bundle.source_path)
    source_hash_before = ""
    source_changed = True
    if source_in_bundle.exists():
        source_hash_before = sha256_file(source_in_bundle)
        source_changed = source_hash_before != bundle.source_sha256

    if bundle.source_sha256 and bundle.source_sha256 == source_hash_before and not force:
        document_path = paths.workspace_root / Path(bundle.document_md)
        if document_path.exists():
            bundle.last_accessed_at = now
            if not dry_run:
                save_manifest(paths, manifest)
                rebuild_category_index(paths, manifest)
            return {
                "ok": True,
                "command": "ensure",
                "status": "ok",
                "warnings": [],
                "errors": [],
                "changed_paths": [],
                "bundle": asdict(bundle),
                "message": f"Bundle `{bundle.id}` already fresh; skipped reconversion.",
            }

    if dry_run:
        return {
            "ok": True,
            "command": "ensure",
            "status": "ok",
            "warnings": warnings,
            "errors": [],
            "changed_paths": [],
            "bundle": asdict(bundle),
            "message": "Dry run complete. No files changed.",
        }

    bundle_root.mkdir(parents=True, exist_ok=True)
    original_dir.mkdir(parents=True, exist_ok=True)
    (bundle_root / "figures").mkdir(parents=True, exist_ok=True)

    if resolved_source != source_in_bundle and _is_loose_category_source(
        paths, inferred_category, resolved_source
    ):
        tmp_destination = original_dir / resolved_source.name
        if source_in_bundle != tmp_destination and source_in_bundle.exists():
            source_in_bundle = tmp_destination
            bundle.source_path = to_rel_posix(paths.workspace_root, source_in_bundle)
        shutil.move(str(resolved_source), str(source_in_bundle))
        changed_paths.append(to_rel_posix(paths.workspace_root, source_in_bundle))

    if not source_in_bundle.exists():
        return _error_result(
            "ensure",
            [f"Expected source file does not exist in bundle: {source_in_bundle}"],
        )

    conversion = convert_rich_document(source_in_bundle, bundle_root / "figures")
    warnings.extend(conversion.warnings)
    document_path = bundle_root / "document.md"
    metadata_path = bundle_root / "metadata.json"
    extraction_path = bundle_root / "extraction.json"

    bundle.source_sha256 = sha256_file(source_in_bundle)
    bundle.source_mtime = _file_mtime_iso(source_in_bundle)
    bundle.converter = conversion.converter
    bundle.status = conversion.status
    bundle.warnings = sorted(set(warnings))
    bundle.last_accessed_at = now
    if conversion.ok:
        bundle.last_processed_at = now
    elif source_changed:
        bundle.status = "needs_reprocess"

    metadata_payload = build_metadata_payload(
        source_name=source_in_bundle.name,
        source_size=source_in_bundle.stat().st_size,
        source_sha256=bundle.source_sha256,
        source_mtime=bundle.source_mtime,
        converter=bundle.converter,
        status=bundle.status,
        warnings=bundle.warnings,
        extraction_report=conversion.extraction_report,
    )

    if conversion.ok:
        atomic_write_text(document_path, conversion.markdown)
        changed_paths.append(to_rel_posix(paths.workspace_root, document_path))
    else:
        placeholder = (
            "# Extraction failed\n\n"
            f"Source: `{bundle.source_path}`\n\n"
            "Conversion could not produce markdown. See `metadata.json` and `extraction.json`.\n"
        )
        atomic_write_text(document_path, placeholder)
        changed_paths.append(to_rel_posix(paths.workspace_root, document_path))

    atomic_write_json(metadata_path, metadata_payload)
    atomic_write_json(extraction_path, conversion.extraction_report)
    changed_paths.extend(
        [
            to_rel_posix(paths.workspace_root, metadata_path),
            to_rel_posix(paths.workspace_root, extraction_path),
        ]
    )

    replace_bundle(manifest, bundle)
    manifest_path = save_manifest(paths, manifest)
    index_file = rebuild_category_index(paths, manifest)
    changed_paths.append(to_rel_posix(paths.workspace_root, manifest_path))
    changed_paths.append(index_file)

    status = "ok" if conversion.ok else "error"
    return {
        "ok": conversion.ok,
        "command": "ensure",
        "status": status,
        "warnings": sorted(set(warnings)),
        "errors": [] if conversion.ok else [conversion.error or "Conversion failed"],
        "changed_paths": sorted(set(changed_paths)),
        "bundle": asdict(bundle),
        "message": f"Ensured bundle `{bundle.id}` in `{inferred_category}`.",
    }


def open_bundle(paths: RuntimePaths, bundle_id: str, category: str | None = None) -> dict:
    found = find_bundle_by_id(paths, bundle_id, category=category)
    if not found:
        return _error_result("open", [f"Bundle not found: {bundle_id}"])
    _, manifest, bundle = found
    bundle.last_accessed_at = utc_now_iso()
    save_manifest(paths, manifest)
    rebuild_category_index(paths, manifest)
    return {
        "ok": True,
        "command": "open",
        "status": "ok",
        "warnings": [],
        "errors": [],
        "changed_paths": [],
        "bundle": asdict(bundle),
        "message": f"Opened `{bundle.id}`.",
    }


def search_bundles(paths: RuntimePaths, query: str, category: str | None = None) -> dict:
    term = query.strip().lower()
    categories = [category] if category else ["syllabi", "reference"]
    matches: list[dict] = []
    changed_paths: list[str] = []
    now = utc_now_iso()
    for item in categories:
        manifest = load_manifest(paths, item)
        category_touched = False
        for bundle in manifest.bundles:
            haystack = " ".join(
                [
                    bundle.id,
                    bundle.title,
                    bundle.source_path,
                    bundle.status,
                    " ".join(bundle.warnings),
                ]
            ).lower()
            if term in haystack:
                bundle.last_accessed_at = now
                category_touched = True
                matches.append(asdict(bundle))
        if category_touched:
            save_manifest(paths, manifest)
            changed_paths.append(f"{item}/_manifest.json")
            changed_paths.append(rebuild_category_index(paths, manifest))
    matches.sort(key=lambda entry: entry["id"])
    return {
        "ok": True,
        "command": "search",
        "status": "ok",
        "warnings": [],
        "errors": [],
        "changed_paths": sorted(set(changed_paths)),
        "matches": matches,
        "message": f"Found {len(matches)} matching bundles.",
    }


def reprocess_bundle(
    paths: RuntimePaths, bundle_id: str, *, force: bool = True, category: str | None = None
) -> dict:
    found = find_bundle_by_id(paths, bundle_id, category=category)
    if not found:
        return _error_result("reprocess", [f"Bundle not found: {bundle_id}"])
    _, _, bundle = found
    source_path = paths.workspace_root / Path(bundle.source_path)
    if not source_path.exists():
        return _error_result("reprocess", [f"Source file is missing: {bundle.source_path}"])
    return ensure_bundle(
        paths,
        str(source_path),
        category=bundle.category,
        dry_run=False,
        force=force,
    )


def set_pin_state(
    paths: RuntimePaths, bundle_id: str, pinned: bool, category: str | None = None
) -> dict:
    found = find_bundle_by_id(paths, bundle_id, category=category)
    if not found:
        return _error_result("pin" if pinned else "unpin", [f"Bundle not found: {bundle_id}"])
    _, manifest, bundle = found
    bundle.pinned = pinned
    bundle.last_accessed_at = utc_now_iso()
    save_manifest(paths, manifest)
    rebuild_category_index(paths, manifest)
    return {
        "ok": True,
        "command": "pin" if pinned else "unpin",
        "status": "ok",
        "warnings": [],
        "errors": [],
        "changed_paths": [],
        "bundle": asdict(bundle),
        "message": f"{'Pinned' if pinned else 'Unpinned'} `{bundle.id}`.",
    }


def status(paths: RuntimePaths) -> dict:
    ensure_base_layout(paths)
    summary = {"categories": {}, "dependencies": detect_dependencies()}
    for category in ["syllabi", "reference"]:
        manifest = load_manifest(paths, category)
        by_status: dict[str, int] = {}
        for bundle in manifest.bundles:
            by_status[bundle.status] = by_status.get(bundle.status, 0) + 1
        summary["categories"][category] = {
            "bundle_count": len(manifest.bundles),
            "status_counts": by_status,
            "manifest_path": f"{category}/_manifest.json",
            "index_path": f"{category}/_index.md",
        }

    return {
        "ok": True,
        "command": "status",
        "status": "ok",
        "warnings": [],
        "errors": [],
        "changed_paths": [],
        "summary": summary,
        "message": "Delamain ingestion status loaded.",
    }


def _build_new_bundle_record(
    *,
    paths: RuntimePaths,
    manifest: CategoryManifest,
    category: str,
    source_path: Path,
    now: str,
) -> BundleRecord:
    base_id = slugify_bundle_id(source_path.stem)
    bundle_id = resolve_collision(
        base_id,
        stable_key=f"{source_path.name}:{source_path.stat().st_size}:{source_path.stat().st_mtime_ns}",
        existing_ids={item.id for item in manifest.bundles},
    )
    bundle_root = paths.category_root(category) / bundle_id
    source_in_bundle = bundle_root / "original" / source_path.name
    return BundleRecord(
        id=bundle_id,
        title=source_path.stem,
        category=category,
        bundle_path=to_rel_posix(paths.workspace_root, bundle_root),
        source_path=to_rel_posix(paths.workspace_root, source_in_bundle),
        source_sha256="",
        source_mtime="",
        document_md=to_rel_posix(paths.workspace_root, bundle_root / "document.md"),
        figures_path=to_rel_posix(paths.workspace_root, bundle_root / "figures"),
        converter="pending",
        status="needs_reprocess",
        placement="normal",
        pinned=category == "syllabi",
        first_seen_at=now,
        last_processed_at="",
        last_accessed_at=now,
        warnings=[],
    )


def _find_bundle_for_source(
    paths: RuntimePaths, manifest: CategoryManifest, source_path: Path
) -> BundleRecord | None:
    source_resolved = source_path.resolve()
    for bundle in manifest.bundles:
        candidate = paths.workspace_root / Path(bundle.source_path)
        if candidate.exists() and candidate.resolve() == source_resolved:
            return bundle
    # Allow targeting loose source by name if already adopted.
    for bundle in manifest.bundles:
        candidate = Path(bundle.source_path).name
        if candidate == source_path.name:
            return bundle
    return None


def _infer_category(paths: RuntimePaths, source_path: Path) -> str | None:
    path = source_path.resolve()
    for category in ["syllabi", "reference"]:
        root = paths.category_root(category).resolve()
        if root in [path, *path.parents]:
            return category
    return None


def _is_loose_category_source(paths: RuntimePaths, category: str, source_path: Path) -> bool:
    return source_path.parent.resolve() == paths.category_root(category).resolve()


def _file_mtime_iso(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat()


def _error_result(command: str, errors: list[str]) -> dict:
    return {
        "ok": False,
        "command": command,
        "status": "error",
        "warnings": [],
        "errors": errors,
        "changed_paths": [],
        "message": errors[0] if errors else "Command failed.",
    }
