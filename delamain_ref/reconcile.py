from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from .index_md import rebuild_category_index
from .manifest import drop_bundle, load_manifest, save_manifest
from .paths import RuntimePaths
from .util import SUPPORTED_INGEST_EXTENSIONS, sha256_file, to_rel_posix, utc_now_iso


def reconcile(
    paths: RuntimePaths, *, category: str | None = None, dry_run: bool = False
) -> dict:
    categories = [category] if category else ["syllabi", "reference"]
    changes: list[dict] = []
    warnings: list[str] = []
    changed_paths: list[str] = []
    unindexed: list[str] = []

    for item in categories:
        result = _reconcile_category(paths, item, dry_run=dry_run)
        changes.extend(result["changes"])
        warnings.extend(result["warnings"])
        unindexed.extend(result["unindexed"])
        if result["changed"]:
            changed_paths.extend(result["changed_paths"])

    return {
        "ok": True,
        "command": "reconcile",
        "status": "ok",
        "warnings": sorted(set(warnings)),
        "errors": [],
        "changed_paths": sorted(set(changed_paths)),
        "changes": changes,
        "unindexed_rich_files": sorted(set(unindexed)),
        "message": f"Reconciled {len(categories)} category folder(s).",
    }


def _reconcile_category(paths: RuntimePaths, category: str, dry_run: bool) -> dict:
    manifest = load_manifest(paths, category)
    root = paths.category_root(category)
    long_term = root / "_long-term"
    long_term.mkdir(parents=True, exist_ok=True)

    fs_bundles = _scan_bundle_dirs(paths, root, placement="normal")
    fs_bundles.update(_scan_bundle_dirs(paths, long_term, placement="long-term"))
    known_ids = set(fs_bundles.keys())
    warnings: list[str] = []
    changes: list[dict] = []
    changed = False

    for bundle in list(manifest.bundles):
        fs_info = fs_bundles.get(bundle.id)
        if fs_info is None:
            drop_bundle(manifest, bundle.id)
            changes.append({"action": "removed_missing_bundle", "id": bundle.id, "category": category})
            changed = True
            continue

        fs_path, fs_placement = fs_info
        if bundle.placement != fs_placement or bundle.bundle_path != to_rel_posix(
            paths.workspace_root, fs_path
        ):
            source_name = Path(bundle.source_path).name
            bundle.placement = fs_placement
            bundle.bundle_path = to_rel_posix(paths.workspace_root, fs_path)
            bundle.document_md = to_rel_posix(paths.workspace_root, fs_path / "document.md")
            bundle.figures_path = to_rel_posix(paths.workspace_root, fs_path / "figures")
            bundle.source_path = to_rel_posix(paths.workspace_root, fs_path / "original" / source_name)
            changes.append({"action": "placement_updated", "id": bundle.id, "placement": fs_placement})
            changed = True

        source = paths.workspace_root / Path(bundle.source_path)
        if source.exists():
            digest = sha256_file(source)
            if digest != bundle.source_sha256:
                bundle.source_sha256 = digest
                bundle.status = "needs_reprocess"
                if "Source hash changed on disk." not in bundle.warnings:
                    bundle.warnings.append("Source hash changed on disk.")
                changes.append({"action": "marked_needs_reprocess", "id": bundle.id})
                changed = True
        else:
            warnings.append(f"Source file missing for bundle `{bundle.id}`: {bundle.source_path}")

    extra_bundle_ids = known_ids - {item.id for item in manifest.bundles}
    for extra_id in sorted(extra_bundle_ids):
        changes.append(
            {
                "action": "untracked_bundle_directory",
                "id": extra_id,
                "path": to_rel_posix(paths.workspace_root, fs_bundles[extra_id][0]),
            }
        )
        warnings.append(f"Untracked bundle directory found: {extra_id}")

    for loose in sorted(root.iterdir(), key=lambda p: p.name.lower()):
        if loose.is_dir():
            continue
        if loose.suffix.lower() in SUPPORTED_INGEST_EXTENSIONS:
            unindexed = to_rel_posix(paths.workspace_root, loose)
            changes.append({"action": "loose_rich_file", "path": unindexed})
            warnings.append(f"Loose rich file not indexed: {unindexed}")

    changed_paths: list[str] = []
    if changed and not dry_run:
        manifest.generated_at = utc_now_iso()
        manifest_file = save_manifest(paths, manifest)
        index_file = rebuild_category_index(paths, manifest)
        changed_paths.extend(
            [to_rel_posix(paths.workspace_root, manifest_file), index_file]
        )
    elif changed:
        changed_paths.extend([f"{category}/_manifest.json", f"{category}/_index.md"])

    return {
        "changed": changed,
        "changes": changes,
        "warnings": warnings,
        "changed_paths": changed_paths,
        "unindexed": [
            asdict_item["path"]
            for asdict_item in changes
            if asdict_item.get("action") == "loose_rich_file"
        ],
    }


def _scan_bundle_dirs(
    paths: RuntimePaths, root: Path, *, placement: str
) -> dict[str, tuple[Path, str]]:
    result: dict[str, tuple[Path, str]] = {}
    if not root.exists():
        return result
    for child in sorted(root.iterdir(), key=lambda p: p.name.lower()):
        if not child.is_dir():
            continue
        if child.name.startswith("_"):
            continue
        if not (child / "original").exists():
            continue
        result[child.name] = (child, placement)
    return result
