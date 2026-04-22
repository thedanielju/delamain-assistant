from __future__ import annotations

import json
from typing import Any

from delamain_backend.db import Database


SETTINGS_DEFAULTS: dict[str, Any] = {
    "context_mode": "normal",
    "title_generation_enabled": True,
    "copilot_budget_hard_override_enabled": False,
}
SETTINGS_KEYS = set(SETTINGS_DEFAULTS) | {"model_default"}
DEFAULT_DISABLED_TOOLS = {"run_shell"}
TOOL_APPROVAL_POLICIES = {"auto", "confirm"}


async def disabled_tools(db: Database) -> set[str]:
    rows = await db.fetchall("SELECT key, value FROM settings WHERE key LIKE 'tool.enabled.%'")
    disabled: set[str] = set(DEFAULT_DISABLED_TOOLS)
    for row in rows:
        tool_name = row["key"].removeprefix("tool.enabled.")
        enabled = json.loads(row["value"])
        if enabled is False:
            disabled.add(tool_name)
        elif enabled is True:
            disabled.discard(tool_name)
    return disabled


async def tool_approval_policy(db: Database, tool_name: str, default: str = "auto") -> str:
    row = await db.fetchone(
        "SELECT value FROM settings WHERE key = ?",
        (f"tool.approval_policy.{tool_name}",),
    )
    if row is None:
        return default
    try:
        value = json.loads(row["value"])
    except json.JSONDecodeError:
        return default
    return value if value in TOOL_APPROVAL_POLICIES else default


async def tool_approval_policies(
    db: Database,
    defaults: dict[str, str],
) -> dict[str, str]:
    rows = await db.fetchall(
        "SELECT key, value FROM settings WHERE key LIKE 'tool.approval_policy.%'"
    )
    policies = dict(defaults)
    for row in rows:
        tool_name = row["key"].removeprefix("tool.approval_policy.")
        try:
            value = json.loads(row["value"])
        except json.JSONDecodeError:
            continue
        if value in TOOL_APPROVAL_POLICIES:
            policies[tool_name] = value
    return policies


async def set_setting(db: Database, key: str, value: Any) -> None:
    await db.execute(
        """
        INSERT INTO settings(key, value, updated_at)
        VALUES (?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        ON CONFLICT(key) DO UPDATE SET
            value = excluded.value,
            updated_at = excluded.updated_at
        """,
        (key, json.dumps(value, sort_keys=True)),
    )
