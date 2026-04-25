from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends

from delamain_backend.api.deps import get_config, get_db
from delamain_backend.budget import copilot_budget_status
from delamain_backend.config import AppConfig
from delamain_backend.db import Database
from delamain_backend.dependencies import assert_litellm_version_allowed, get_litellm_version
from delamain_backend.schemas import HealthOut
from delamain_backend.system_status import system_status

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthOut)
async def health(config: AppConfig = Depends(get_config), db: Database = Depends(get_db)):
    litellm_version = get_litellm_version()
    litellm_allowed = True
    litellm_error = None
    try:
        assert_litellm_version_allowed(litellm_version)
    except Exception as exc:
        litellm_allowed = False
        litellm_error = str(exc)

    helpers = {
        "now": _helper_status(config.paths.llm_workspace / "bin" / "now"),
        "delamain_ref": _helper_status(config.paths.llm_workspace / "bin" / "delamain-ref"),
        "delamain_vault_index": _helper_status(
            config.paths.llm_workspace / "bin" / "delamain-vault-index"
        ),
    }
    sqlite_ok = await db.healthcheck()
    budget = await copilot_budget_status(config, db)
    system = await system_status(db)
    return {
        "status": "ok" if sqlite_ok and litellm_allowed else "degraded",
        "sqlite": {"path": str(config.database.path), "ok": sqlite_ok},
        "litellm": {
            "version": litellm_version,
            "known_bad_blocked": litellm_allowed,
            "error": litellm_error,
        },
        "config": {
            "host": config.server.host,
            "port": config.server.port,
            "model_default": config.models.default,
            "model_calls_enabled": config.runtime.enable_model_calls,
        },
        "budget": budget,
        "helpers": helpers,
        "system": system,
    }


def _helper_status(path: Path) -> dict:
    return {"path": str(path), "exists": path.exists(), "executable": path.exists() and path.stat().st_mode & 0o111 != 0}
