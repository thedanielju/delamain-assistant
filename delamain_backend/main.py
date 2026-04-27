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
from delamain_backend.maintenance import run_startup_cleanup
from delamain_backend.security.auth import CloudflareAccessValidator, install_auth_middleware
from delamain_backend.structured_logging import configure_logging, install_request_logging
from delamain_backend.uploads import validate_upload_storage_root
from delamain_backend.vault_heartbeat import VaultIndexHeartbeat
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
        configure_logging()
        assert_litellm_version_allowed()
        validate_upload_storage_root(loaded_config)
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
        app.state.vault_index_heartbeat = VaultIndexHeartbeat(loaded_config, db=db)
        app.state.vault_index_heartbeat_task = asyncio.create_task(
            app.state.vault_index_heartbeat.run_forever()
        )
        app.state.startup_cleanup = run_startup_cleanup(loaded_config)
        await run_manager.recover_on_startup()
        app.state.worker_reconciliation = await worker_manager.reconcile_on_startup()
        try:
            yield
        finally:
            enrichment_task = getattr(app.state, "vault_enrichment_batch_task", None)
            if enrichment_task is not None and not enrichment_task.done():
                enrichment_task.cancel()
                try:
                    await enrichment_task
                except asyncio.CancelledError:
                    pass
            await run_manager.shutdown()
            app.state.vault_index_heartbeat_task.cancel()
            try:
                await app.state.vault_index_heartbeat_task
            except asyncio.CancelledError:
                pass
            app.state.event_reaper_task.cancel()
            try:
                await app.state.event_reaper_task
            except asyncio.CancelledError:
                pass
            await db.close()

    app = FastAPI(title="DELAMAIN Backend", version="0.1.0", lifespan=lifespan)
    install_request_logging(app)
    install_auth_middleware(app, CloudflareAccessValidator((config or load_config()).auth))
    app.include_router(api_router)
    return app


app = create_app()
