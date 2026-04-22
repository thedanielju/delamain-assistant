from __future__ import annotations

import shutil
import time
from pathlib import Path

from delamain_backend.config import AppConfig


def run_startup_cleanup(config: AppConfig) -> dict[str, int]:
    return {
        "action_outputs_removed": cleanup_old_children(
            config.database.path.parent / "action-outputs",
            retention_days=config.maintenance.action_output_retention_days,
        ),
        "context_backups_removed": cleanup_old_children(
            config.database.path.parent / "context-backups",
            retention_days=config.maintenance.context_backup_retention_days,
            recursive_files=True,
        ),
    }


def cleanup_old_children(
    root: Path, *, retention_days: int, recursive_files: bool = False
) -> int:
    if retention_days <= 0 or not root.exists():
        return 0
    cutoff = time.time() - retention_days * 24 * 60 * 60
    if recursive_files:
        return _cleanup_old_files(root, cutoff)
    removed = 0
    for child in root.iterdir():
        try:
            if child.stat().st_mtime >= cutoff:
                continue
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
            removed += 1
        except OSError:
            continue
    return removed


def _cleanup_old_files(root: Path, cutoff: float) -> int:
    removed = 0
    for child in root.rglob("*"):
        try:
            if not child.is_file() or child.stat().st_mtime >= cutoff:
                continue
            child.unlink()
            removed += 1
        except OSError:
            continue
    for child in sorted((path for path in root.rglob("*") if path.is_dir()), reverse=True):
        try:
            child.rmdir()
        except OSError:
            continue
    return removed
