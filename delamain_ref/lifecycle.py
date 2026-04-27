from __future__ import annotations

import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .index_md import rebuild_category_index
from .manifest import load_manifest, save_manifest
from .paths import RuntimePaths
from .util import parse_iso8601, to_rel_posix


def move_inactive_to_long_term(
    paths: RuntimePaths,
    *,
    days: int,
    category: str | None = None,
    dry_run: bool = False,
) -> dict:
    categories = [category] if category else ["syllabi", "reference"]
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    moved: list[dict] = []
    changed_paths: list[str] = []
    warnings: list[str] = []

    for item in categories:
        manifest = load_manifest(paths, item)
        root = paths.category_root(item)
        long_term_root = root / "_long-term"
        long_term_root.mkdir(parents=True, exist_ok=True)
        category_changed = False

        for bundle in manifest.bundles:
            if bundle.placement != "normal" or bundle.pinned:
                continue
            last_seen = (
                parse_iso8601(bundle.last_accessed_at)
                or parse_iso8601(bundle.last_processed_at)
                or parse_iso8601(bundle.first_seen_at)
            )
            if not last_seen:
                warnings.append(f"Unable to parse timestamps for `{bundle.id}`.")
                continue
            if last_seen > cutoff:
                continue

            src = paths.workspace_root / Path(bundle.bundle_path)
            dst = long_term_root / bundle.id
            if not src.exists():
                warnings.append(f"Bundle path missing for `{bundle.id}`: {bundle.bundle_path}")
                continue
            if dst.exists():
                warnings.append(f"Long-term target already exists: {to_rel_posix(paths.workspace_root, dst)}")
                continue

            if not dry_run:
                shutil.move(str(src), str(dst))
            bundle.placement = "long-term"
            bundle.bundle_path = to_rel_posix(paths.workspace_root, dst)
            bundle.document_md = to_rel_posix(paths.workspace_root, dst / "document.md")
            bundle.figures_path = to_rel_posix(paths.workspace_root, dst / "figures")
            bundle.source_path = to_rel_posix(
                paths.workspace_root, dst / "original" / Path(bundle.source_path).name
            )
            category_changed = True
            moved.append({"id": bundle.id, "category": item, "to": bundle.bundle_path})

        if category_changed and not dry_run:
            changed_paths.append(to_rel_posix(paths.workspace_root, save_manifest(paths, manifest)))
            changed_paths.append(rebuild_category_index(paths, manifest))
        elif category_changed:
            changed_paths.append(f"{item}/_manifest.json")
            changed_paths.append(f"{item}/_index.md")

    return {
        "ok": True,
        "command": "long-term-inactive",
        "status": "ok",
        "warnings": warnings,
        "errors": [],
        "changed_paths": sorted(set(changed_paths)),
        "moved": moved,
        "message": f"Moved {len(moved)} bundle(s) to long-term.",
    }
