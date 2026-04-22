from __future__ import annotations

import json
import re
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from delamain_backend.config import AppConfig
from delamain_backend.errors import ToolPolicyDenied

FOLDER_IDS = ("vault-combo", "7lf7x-urjpx", "llm-workspace")
EXPECTED_DEVICES = ("mac", "serrano", "winpc", "iphone")


def syncthing_summary(config: AppConfig) -> dict[str, Any]:
    reports = _load_reports(config)
    devices = [_device_summary(report) for report in reports]
    known_hosts = {device["host"] for device in devices}
    for host in EXPECTED_DEVICES:
        if host not in known_hosts and not _host_alias_present(host, known_hosts):
            devices.append(
                {
                    "host": host,
                    "status": "unknown",
                    "timestamp": None,
                    "syncthing_available": False,
                    "conflict_count": None,
                    "junk_count": None,
                    "folders": [],
                    "connections": [],
                    "source": "expected_device",
                }
            )
    return {
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "source": "sync_guard_reports",
        "devices": devices,
    }


def syncthing_conflicts(config: AppConfig) -> dict[str, Any]:
    reports = _load_reports(config)
    grouped: dict[str, dict[str, Any]] = {}
    for report in reports:
        host = str(report.get("health", {}).get("host") or report["path"].parent.name)
        for item in report.get("resolver", {}).get("review_items", []) or []:
            path = str(item.get("conflict") or item.get("path") or "")
            if not path:
                continue
            entry = grouped.setdefault(
                path,
                {
                    "id": _conflict_id(path),
                    "path": path,
                    "canonical_path": item.get("canonical"),
                    "folder_id": _folder_id_for_path(path),
                    "devices": [],
                    "mtimes": {},
                    "reason": item.get("reason"),
                    "review_dir": item.get("review_dir"),
                },
            )
            entry["devices"].append(host)
            mtime = _mtime(path)
            if mtime is not None:
                entry["mtimes"][host] = mtime
    return {
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "source": "sync_guard_reports",
        "conflicts": sorted(grouped.values(), key=lambda item: item["path"]),
    }


def resolve_syncthing_conflict(
    config: AppConfig,
    *,
    path: str,
    action: str,
    note: str | None = None,
) -> dict[str, Any]:
    if action not in {"keep_canonical", "keep_conflict", "keep_both", "stage_review"}:
        raise ToolPolicyDenied("Unsupported Syncthing conflict resolution action")
    conflict = _resolve_allowed_path(config, path)
    if not conflict.exists() or not conflict.is_file():
        raise ToolPolicyDenied(f"Conflict file not found: {conflict}")
    canonical = _canonical_for_conflict(conflict)
    if canonical is not None:
        canonical = _resolve_allowed_path(config, str(canonical))

    backup_dir = _backup_root(config) / datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    backup_dir = backup_dir / f"{action}-{uuid.uuid4().hex[:8]}"
    backup_dir.mkdir(parents=True, exist_ok=False)

    backups = []
    backups.append(_backup_file(conflict, backup_dir, "conflict"))
    if canonical is not None and canonical.exists():
        backups.append(_backup_file(canonical, backup_dir, "canonical"))

    result_path: Path | None = None
    if action == "keep_canonical":
        conflict.unlink()
    elif action == "keep_conflict":
        if canonical is None:
            raise ToolPolicyDenied("Could not infer canonical path for conflict")
        canonical.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(conflict, canonical)
        conflict.unlink()
        result_path = canonical
    elif action == "keep_both":
        if canonical is None:
            raise ToolPolicyDenied("Could not infer canonical path for conflict")
        result_path = _next_available_path(_both_copy_path(canonical))
        shutil.copy2(conflict, result_path)
        conflict.unlink()
    elif action == "stage_review":
        result_path = conflict

    manifest = {
        "action": action,
        "note": note,
        "conflict_path": str(conflict),
        "canonical_path": str(canonical) if canonical is not None else None,
        "result_path": str(result_path) if result_path is not None else None,
        "backups": backups,
        "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }
    (backup_dir / "resolution.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return {
        "status": "resolved" if action != "stage_review" else "staged",
        "action": action,
        "path": str(conflict),
        "canonical_path": str(canonical) if canonical is not None else None,
        "result_path": str(result_path) if result_path is not None else None,
        "backup_dir": str(backup_dir),
        "backups": backups,
    }


def _load_reports(config: AppConfig) -> list[dict[str, Any]]:
    base = config.paths.llm_workspace / "health" / "sync-guard" / "hosts"
    reports: list[dict[str, Any]] = []
    if not base.exists():
        return reports
    for path in sorted(base.glob("*/latest.json")):
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(loaded, dict):
            loaded["path"] = path
            reports.append(loaded)
    return reports


def _backup_root(config: AppConfig) -> Path:
    return config.database.path.parent / "syncthing-conflict-resolution-backups"


def _backup_file(path: Path, backup_dir: Path, label: str) -> dict[str, Any]:
    target = backup_dir / f"{label}-{path.name}"
    shutil.copy2(path, target)
    return {"label": label, "source": str(path), "backup": str(target)}


def _resolve_allowed_path(config: AppConfig, raw: str) -> Path:
    path = Path(raw).expanduser().resolve(strict=False)
    roots = (
        config.paths.vault,
        config.paths.sensitive,
        config.paths.llm_workspace,
    )
    if not any(_inside(path, root) for root in roots):
        raise ToolPolicyDenied(f"Path is outside DELAMAIN roots: {path}")
    return path


def _canonical_for_conflict(path: Path) -> Path | None:
    name = path.name
    cleaned = re.sub(r"\.sync-conflict-[^.]+", "", name)
    if cleaned == name:
        return None
    return path.with_name(cleaned)


def _both_copy_path(canonical: Path) -> Path:
    return canonical.with_name(f"{canonical.stem}.conflict-copy{canonical.suffix}")


def _next_available_path(path: Path) -> Path:
    if not path.exists():
        return path
    for index in range(2, 1000):
        candidate = path.with_name(f"{path.stem}-{index}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise ToolPolicyDenied(f"Could not find available keep_both path near {path}")


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root.expanduser().resolve(strict=False))
        return True
    except ValueError:
        return False


def _conflict_id(path: str) -> str:
    import hashlib

    return hashlib.sha256(path.encode("utf-8")).hexdigest()[:16]


def _device_summary(report: dict[str, Any]) -> dict[str, Any]:
    health = report.get("health", {}) if isinstance(report.get("health"), dict) else {}
    syncthing = health.get("syncthing", {}) if isinstance(health.get("syncthing"), dict) else {}
    folders = []
    for folder_id, info in sorted((syncthing.get("folders") or {}).items()):
        if not isinstance(info, dict):
            continue
        folders.append(
            {
                "folder_id": folder_id,
                "state": info.get("state"),
                "need_total_items": info.get("needTotalItems"),
                "need_bytes": info.get("needBytes"),
                "errors": info.get("errors"),
                "pull_errors": info.get("pullErrors"),
                "global_total_items": info.get("globalTotalItems"),
                "local_total_items": info.get("localTotalItems"),
            }
        )
    status = "unknown"
    if syncthing.get("available") is True:
        status = "ok"
        if health.get("conflict_count") or any(
            (folder.get("need_total_items") or 0) > 0
            or (folder.get("errors") or 0) > 0
            or (folder.get("pull_errors") or 0) > 0
            for folder in folders
        ):
            status = "degraded"
    elif syncthing.get("available") is False:
        status = "unavailable"
    return {
        "host": health.get("host") or report["path"].parent.name,
        "status": status,
        "timestamp": health.get("timestamp"),
        "syncthing_available": bool(syncthing.get("available")),
        "conflict_count": health.get("conflict_count"),
        "junk_count": health.get("junk_count"),
        "folders": folders,
        "connections": _connections(syncthing.get("connections") or {}),
        "source": str(report["path"]),
    }


def _connections(connections: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for device_id, info in sorted(connections.items()):
        if not isinstance(info, dict):
            continue
        rows.append(
            {
                "device_id": device_id,
                "connected": bool(info.get("connected")),
                "address": info.get("address"),
                "client_version": info.get("clientVersion"),
                "paused": bool(info.get("paused")),
                "at": info.get("at"),
            }
        )
    return rows


def _folder_id_for_path(path: str) -> str | None:
    lowered = path.lower()
    for folder_id in FOLDER_IDS:
        if folder_id.lower() in lowered:
            return folder_id
    if "obsidian sensitive" in lowered or "sensitive" in lowered:
        return "7lf7x-urjpx"
    if "llm-workspace" in lowered:
        return "llm-workspace"
    if "vault" in lowered:
        return "vault-combo"
    return None


def _mtime(path: str) -> str | None:
    try:
        stat = Path(path).expanduser().stat()
    except OSError:
        return None
    return datetime.fromtimestamp(stat.st_mtime, UTC).isoformat().replace("+00:00", "Z")


def _host_alias_present(expected: str, known_hosts: set[str]) -> bool:
    aliases = {
        "mac": {"mac", "macbook", "daniels-macbook"},
        "winpc": {"winpc", "desktop-d8brose"},
        "iphone": {"iphone"},
        "serrano": {"serrano"},
    }
    return bool({host.lower() for host in known_hosts} & aliases.get(expected, {expected}))
