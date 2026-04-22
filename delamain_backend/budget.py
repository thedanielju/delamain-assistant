from __future__ import annotations

from datetime import UTC, datetime
import json
from typing import Any

from delamain_backend.config import AppConfig
from delamain_backend.db import Database

COPILOT_ROUTE_PREFIX = "github_copilot/"
OVERRIDE_SETTING = "copilot_budget_hard_override_enabled"


def _month_start_utc() -> str:
    now = datetime.now(UTC)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%S.%fZ"
    )


async def copilot_budget_status(config: AppConfig, db: Database) -> dict[str, Any]:
    row = await db.fetchone(
        """
        SELECT COUNT(*) AS count
        FROM model_calls
        WHERE status = 'completed'
          AND model_route LIKE 'github_copilot/%'
          AND created_at >= ?
        """,
        (_month_start_utc(),),
    )
    used = int(row["count"] or 0) if row else 0
    limit = max(0, int(config.copilot_budget.monthly_premium_requests))
    percent = round((used / limit) * 100, 2) if limit else 0.0
    if limit and percent >= config.copilot_budget.hard_threshold_percent:
        status = "hard"
    elif limit and percent >= config.copilot_budget.soft_threshold_percent:
        status = "soft"
    else:
        status = "ok"
    override_enabled = await copilot_budget_hard_override_enabled(db)
    return {
        "period": "current_month_utc",
        "used_premium_requests": used,
        "monthly_premium_requests": limit,
        "percent_used": percent,
        "soft_threshold_percent": config.copilot_budget.soft_threshold_percent,
        "hard_threshold_percent": config.copilot_budget.hard_threshold_percent,
        "status": status,
        "hard_override_enabled": override_enabled,
        "enforced": status == "hard" and not override_enabled,
    }


def is_copilot_route(model_route: str) -> bool:
    return str(model_route or "").startswith(COPILOT_ROUTE_PREFIX)


async def copilot_budget_hard_override_enabled(db: Database) -> bool:
    row = await db.fetchone("SELECT value FROM settings WHERE key = ?", (OVERRIDE_SETTING,))
    if row is None:
        return False
    try:
        return bool(json.loads(row["value"]))
    except (TypeError, json.JSONDecodeError):
        return False
