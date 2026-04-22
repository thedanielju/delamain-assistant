from __future__ import annotations

from fastapi import Request

from delamain_backend.agent import RunManager
from delamain_backend.config import AppConfig
from delamain_backend.db import Database
from delamain_backend.events import EventBus
from delamain_backend.workers import WorkerManager
from delamain_backend.workers.registry import WorkerTypeRegistry


def get_config(request: Request) -> AppConfig:
    return request.app.state.config


def get_db(request: Request) -> Database:
    return request.app.state.db


def get_bus(request: Request) -> EventBus:
    return request.app.state.bus


def get_run_manager(request: Request) -> RunManager:
    return request.app.state.run_manager


def get_worker_registry(request: Request) -> WorkerTypeRegistry:
    return request.app.state.worker_registry


def get_worker_manager(request: Request) -> WorkerManager:
    return request.app.state.worker_manager
