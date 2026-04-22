from __future__ import annotations

from fastapi import APIRouter, Depends

from delamain_backend.api.deps import get_config
from delamain_backend.config import AppConfig
from delamain_backend.syncthing_status import syncthing_conflicts, syncthing_summary

router = APIRouter(tags=["syncthing"])


@router.get("/syncthing/summary")
async def get_syncthing_summary(config: AppConfig = Depends(get_config)):
    return syncthing_summary(config)


@router.get("/syncthing/conflicts")
async def get_syncthing_conflicts(config: AppConfig = Depends(get_config)):
    return syncthing_conflicts(config)
