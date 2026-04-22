from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI

from delamain_backend.agent import RunManager
from delamain_backend.agent.litellm_client import ModelClient
from delamain_backend.api import api_router
from delamain_backend.config import AppConfig, load_config
from delamain_backend.db import Database
from delamain_backend.dependencies import assert_litellm_version_allowed
from delamain_backend.events import EventBus
from delamain_backend.workers import WorkerManager, default_worker_registry


async def _reap_event_subscribers(bus: EventBus) -> None:
    try:
        while True:
            await bus.reap_stale_subscribers()
            await asyncio.sleep(60)
    except asyncio.CancelledError:
        raise


def create_app(config: AppConfig | None = None, model_client: ModelClient | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        loaded_config = config or load_config()
        assert_litellm_version_allowed()
        db = Database(loaded_config.database.path)
        await db.connect()
        await db.migrate()
        bus = EventBus(db)
        worker_registry = default_worker_registry(loaded_config)
        worker_manager = WorkerManager(
            config=loaded_config,
            db=db,
            bus=bus,
            registry=worker_registry,
        )
        run_manager = RunManager(
            config=loaded_config,
            db=db,
            bus=bus,
            model_client=model_client,
        )
        app.state.config = loaded_config
        app.state.db = db
        app.state.bus = bus
        app.state.run_manager = run_manager
        app.state.worker_registry = worker_registry
        app.state.worker_manager = worker_manager
        app.state.event_reaper_task = asyncio.create_task(_reap_event_subscribers(bus))
        await run_manager.recover_on_startup()
        try:
            yield
        finally:
            app.state.event_reaper_task.cancel()
            try:
                await app.state.event_reaper_task
            except asyncio.CancelledError:
                pass
            await db.close()

    app = FastAPI(title="DELAMAIN Backend", version="0.1.0", lifespan=lifespan)
    app.include_router(api_router)
    return app


app = create_app()
