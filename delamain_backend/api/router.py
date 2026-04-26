from fastapi import APIRouter

from . import (
    action_runs,
    actions,
    context,
    conversations,
    folders,
    health,
    permissions,
    runs,
    settings,
    streams,
    syncthing,
    usage,
    vault,
    workers,
)

api_router = APIRouter(prefix="/api")
api_router.include_router(action_runs.router)
api_router.include_router(actions.router)
api_router.include_router(context.router)
api_router.include_router(health.router)
api_router.include_router(conversations.router)
api_router.include_router(folders.router)
api_router.include_router(permissions.router)
api_router.include_router(runs.router)
api_router.include_router(settings.router)
api_router.include_router(streams.router)
api_router.include_router(syncthing.router)
api_router.include_router(usage.router)
api_router.include_router(vault.router)
api_router.include_router(workers.router)
