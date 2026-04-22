from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from delamain_backend.config import AppConfig

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
