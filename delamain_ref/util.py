from __future__ import annotations

import hashlib
import json
import os
import re
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SUPPORTED_INGEST_EXTENSIONS = {".pdf", ".docx", ".rtf", ".odt", ".txt", ".md"}
EXCLUDED_INGEST_EXTENSIONS = set()


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def to_rel_posix(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}.{time.time_ns()}")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def atomic_write_json(path: Path, payload: Any) -> None:
    content = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    atomic_write_text(path, content)


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def slugify_bundle_id(stem: str) -> str:
    normalized = unicodedata.normalize("NFKD", stem).encode("ascii", "ignore").decode()
    lowered = normalized.lower()
    lowered = re.sub(r"[^a-z0-9]+", "-", lowered)
    lowered = re.sub(r"-{2,}", "-", lowered).strip("-")
    return lowered or "document"


def resolve_collision(base_id: str, stable_key: str, existing_ids: set[str]) -> str:
    if base_id not in existing_ids:
        return base_id
    suffix = hashlib.sha256(stable_key.encode("utf-8")).hexdigest()[:8]
    candidate = f"{base_id}-{suffix}"
    if candidate not in existing_ids:
        return candidate
    i = 2
    while True:
        candidate = f"{base_id}-{suffix}-{i}"
        if candidate not in existing_ids:
            return candidate
        i += 1


def parse_iso8601(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
