from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from delamain_backend.config import AppConfig

CLOCK_BLOCK_START = "BEGIN:clock"
CLOCK_BLOCK_END = "END:clock"


@dataclass(frozen=True)
class LoadedContext:
    items: list[dict]
    prompt_messages: list[dict[str, str]]
    clock_refresh: dict[str, Any] | None = None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _file_metadata(
    path: Path,
    *,
    mode: str,
    included: bool,
    content_override: str | None = None,
) -> dict:
    if content_override is not None:
        data = content_override.encode("utf-8")
        return {
            "path": str(path),
            "mode": mode,
            "included": included,
            "missing": False,
            "byte_count": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        }
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


def load_context_for_run(config: AppConfig, context_mode: str) -> LoadedContext:
    system_path = config.paths.system_context
    system_text = system_path.read_text(encoding="utf-8") if system_path.exists() else ""
    refreshed_system_text, clock_refresh = _refresh_system_clock_context(config, system_text)
    items = [
        _file_metadata(
            system_path,
            mode="system_context",
            included=True,
            content_override=refreshed_system_text if system_path.exists() else None,
        )
    ]
    prompt_messages: list[dict[str, str]] = []
    if system_path.exists():
        prompt_messages.append({"role": "system", "content": refreshed_system_text})
    if context_mode != "blank_slate":
        continuity = config.paths.short_term_continuity
        continuity_exists = continuity.exists()
        items.append(
            _file_metadata(
                continuity,
                mode="short_term_continuity",
                included=continuity_exists,
            )
        )
        if continuity_exists:
            prompt_messages.append(
                {"role": "system", "content": continuity.read_text(encoding="utf-8")}
            )
    return LoadedContext(
        items=items,
        prompt_messages=prompt_messages,
        clock_refresh=clock_refresh,
    )


def context_items_for_run(config: AppConfig, context_mode: str) -> list[dict]:
    return load_context_for_run(config, context_mode).items


def _refresh_system_clock_context(
    config: AppConfig,
    content: str,
) -> tuple[str, dict[str, Any] | None]:
    if not content:
        return content, None
    heartbeat_path = config.paths.llm_workspace / "health" / "mac-heartbeat.json"
    heartbeat = _read_heartbeat(heartbeat_path)
    timezone_name = str(heartbeat.get("timezone_name") or "").strip()
    if not timezone_name:
        return content, None
    try:
        current_dt = _utc_now().astimezone(ZoneInfo(timezone_name))
    except Exception:
        return content, None
    timezone_abbrev = str(heartbeat.get("timezone_abbrev") or current_dt.tzname() or "").strip()
    if not timezone_abbrev:
        return content, None
    expected_line = f"{current_dt:%Y-%m-%d %A} · {timezone_name} ({timezone_abbrev})"
    replaced = _replace_clock_block(content, expected_line)
    if replaced is None:
        return content, None
    existing_line, refreshed_content = replaced
    if existing_line == expected_line:
        return content, None
    return refreshed_content, {
        "path": str(config.paths.system_context),
        "heartbeat_path": str(heartbeat_path),
        "previous_clock": existing_line,
        "clock": expected_line,
        "timezone_name": timezone_name,
        "timezone_abbrev": timezone_abbrev,
    }


def _read_heartbeat(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _replace_clock_block(content: str, expected_line: str) -> tuple[str, str] | None:
    lines = content.splitlines(keepends=True)
    start_index = next(
        (index for index, line in enumerate(lines) if CLOCK_BLOCK_START in line),
        None,
    )
    if start_index is None:
        return None
    end_index = next(
        (index for index in range(start_index + 1, len(lines)) if CLOCK_BLOCK_END in lines[index]),
        None,
    )
    if end_index is None or end_index <= start_index:
        return None
    existing_line = "".join(lines[start_index + 1 : end_index]).strip()
    refreshed_lines = lines[: start_index + 1] + [expected_line + "\n"] + lines[end_index:]
    return existing_line, "".join(refreshed_lines)
