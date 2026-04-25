from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from delamain_backend.api.audit import audit_event
from delamain_backend.api.deps import get_bus, get_config, get_db
from delamain_backend.budget import copilot_budget_status
from delamain_backend.config import AppConfig
from delamain_backend.db import Database
from delamain_backend.events import EventBus
from delamain_backend.schemas import SettingsPatch, ToolSettingPatch
from delamain_backend.settings_store import (
    SETTINGS_DEFAULTS,
    SETTINGS_KEYS,
    TOOL_APPROVAL_POLICIES,
    allowed_model_routes,
    disabled_tools,
    set_setting,
    tool_approval_policies,
)
from delamain_backend.tools import default_tool_registry

router = APIRouter(tags=["settings"])

@router.get("/settings")
async def get_settings(
    config: AppConfig = Depends(get_config),
    db: Database = Depends(get_db),
):
    return await _settings_payload(config, db)


@router.patch("/settings")
async def patch_settings(
    payload: SettingsPatch,
    config: AppConfig = Depends(get_config),
    db: Database = Depends(get_db),
    bus: EventBus = Depends(get_bus),
):
    for key, value in payload.values.items():
        if key not in SETTINGS_KEYS:
            raise HTTPException(status_code=400, detail=f"Unsupported setting: {key}")
        _validate_setting(config, key, value)
        await set_setting(db, key, value)
    await audit_event(
        db=db,
        bus=bus,
        conversation_id=payload.conversation_id,
        action="settings.updated",
        summary="Settings updated",
        payload={"keys": sorted(payload.values)},
    )
    return await _settings_payload(config, db)


@router.get("/settings/models")
async def get_model_settings(config: AppConfig = Depends(get_config)):
    return {
        "default": config.models.default,
        "fallback_high_volume": config.models.fallback_high_volume,
        "fallback_cheap": config.models.fallback_cheap,
        "paid_fallback": config.models.paid_fallback,
    }


@router.get("/settings/budget")
async def get_budget_settings(
    config: AppConfig = Depends(get_config),
    db: Database = Depends(get_db),
):
    return {"copilot_budget": await copilot_budget_status(config, db)}


@router.get("/settings/tools")
async def get_tool_settings(
    config: AppConfig = Depends(get_config),
    db: Database = Depends(get_db),
):
    registry = default_tool_registry(config)
    return {"tools": await _tool_settings(db, registry)}


@router.patch("/settings/tools/{tool_name}")
async def patch_tool_setting(
    tool_name: str,
    payload: ToolSettingPatch,
    config: AppConfig = Depends(get_config),
    db: Database = Depends(get_db),
    bus: EventBus = Depends(get_bus),
):
    registry = default_tool_registry(config)
    if not registry.has_tool(tool_name):
        raise HTTPException(status_code=404, detail="Tool not found")
    if payload.enabled is None and payload.approval_policy is None:
        raise HTTPException(status_code=400, detail="enabled or approval_policy is required")
    if payload.approval_policy is not None and payload.approval_policy not in TOOL_APPROVAL_POLICIES:
        raise HTTPException(
            status_code=400,
            detail=f"approval_policy must be one of {sorted(TOOL_APPROVAL_POLICIES)}",
        )
    if payload.enabled is not None:
        await set_setting(db, f"tool.enabled.{tool_name}", bool(payload.enabled))
    if payload.approval_policy is not None:
        await set_setting(db, f"tool.approval_policy.{tool_name}", payload.approval_policy)
    await audit_event(
        db=db,
        bus=bus,
        conversation_id=payload.conversation_id,
        action="settings.tool_updated",
        summary=f"Tool {tool_name} settings updated",
        payload={
            "tool": tool_name,
            "enabled": payload.enabled,
            "approval_policy": payload.approval_policy,
        },
    )
    return {
        "tool": tool_name,
        "enabled": payload.enabled,
        "approval_policy": payload.approval_policy,
    }


async def _settings_payload(config: AppConfig, db: Database) -> dict:
    settings = dict(SETTINGS_DEFAULTS)
    settings["model_default"] = config.models.default
    rows = await db.fetchall("SELECT key, value FROM settings")
    for row in rows:
        if row["key"] in SETTINGS_KEYS:
            import json

            settings[row["key"]] = json.loads(row["value"])
    return {"settings": settings}


async def _tool_settings(db: Database, registry) -> list[dict]:
    disabled = await disabled_tools(db)
    metadata = registry.metadata()
    policies = await tool_approval_policies(
        db,
        {
            item["name"]: item["approval_policy_default"]
            for item in metadata
        },
    )
    return [
        {
            **item,
            "enabled": item["name"] not in disabled,
            "approval_policy": policies.get(item["name"], item["approval_policy_default"]),
            "approval_policy_options": sorted(TOOL_APPROVAL_POLICIES),
        }
        for item in metadata
    ]


def _validate_setting(config: AppConfig, key: str, value: Any) -> None:
    if key == "context_mode" and value not in {"normal", "blank_slate"}:
        raise HTTPException(status_code=400, detail="context_mode must be normal or blank_slate")
    if key == "title_generation_enabled" and not isinstance(value, bool):
        raise HTTPException(status_code=400, detail="title_generation_enabled must be boolean")
    if key == "copilot_budget_hard_override_enabled" and not isinstance(value, bool):
        raise HTTPException(
            status_code=400,
            detail="copilot_budget_hard_override_enabled must be boolean",
        )
    if key == "model_default" and value not in allowed_model_routes(config):
        raise HTTPException(status_code=400, detail="Unsupported model_default")
    if key == "task_model" and value not in allowed_model_routes(config):
        raise HTTPException(status_code=400, detail="Unsupported task_model")
