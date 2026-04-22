from __future__ import annotations

import hashlib
from pathlib import Path

from delamain_backend.config import AppConfig


def _file_metadata(path: Path, *, mode: str, included: bool) -> dict:
    if not path.exists():
        return {
            "path": str(path),
            "mode": mode,
            "included": False,
            "missing": True,
            "byte_count": None,
            "sha256": None,
        }
    data = path.read_bytes()
    return {
        "path": str(path),
        "mode": mode,
        "included": included,
        "missing": False,
        "byte_count": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def context_items_for_run(config: AppConfig, context_mode: str) -> list[dict]:
    items = [
        _file_metadata(config.paths.system_context, mode="system_context", included=True)
    ]
    if context_mode != "blank_slate":
        continuity = config.paths.short_term_continuity
        items.append(
            _file_metadata(
                continuity,
                mode="short_term_continuity",
                included=continuity.exists(),
            )
        )
    return items
