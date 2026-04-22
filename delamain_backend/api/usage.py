from __future__ import annotations

from fastapi import APIRouter, Depends

from delamain_backend.api.deps import get_config, get_db
from delamain_backend.config import AppConfig
from delamain_backend.db import Database
from delamain_backend.subscription_status import subscription_status
from delamain_backend.usage import usage_summary

router = APIRouter(tags=["usage"])


@router.get("/usage")
async def get_usage(config: AppConfig = Depends(get_config), db: Database = Depends(get_db)):
    return await usage_summary(config, db)


@router.get("/usage/subscriptions")
async def get_usage_subscriptions(config: AppConfig = Depends(get_config), refresh: bool = False):
    return subscription_status(config, force_refresh=refresh)
