from __future__ import annotations

import json
from typing import Any

from delamain_backend.db import Database


SETTINGS_DEFAULTS: dict[str, Any] = {
    "context_mode": "normal",
    "title_generation_enabled": True,
}
SETTINGS_KEYS = set(SETTINGS_DEFAULTS) | {"model_default"}


async def disabled_tools(db: Database) -> set[str]:
    rows = await db.fetchall("SELECT key, value FROM settings WHERE key LIKE 'tool.enabled.%'")
    disabled: set[str] = set()
    for row in rows:
        enabled = json.loads(row["value"])
        if enabled is False:
            disabled.add(row["key"].removeprefix("tool.enabled."))
    return disabled


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
