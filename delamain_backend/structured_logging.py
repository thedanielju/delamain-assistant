from __future__ import annotations

import json
import logging
import os
import time
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, Request, Response


LOG_RECORD_RESERVED = {
    "args",
    "asctime",
    "created",
    "exc_info",
    "exc_text",
    "filename",
    "funcName",
    "levelname",
    "levelno",
    "lineno",
    "module",
    "msecs",
    "message",
    "msg",
    "name",
    "pathname",
    "process",
    "processName",
    "relativeCreated",
    "stack_info",
    "thread",
    "threadName",
    "taskName",
}


class JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "level": record.levelname.lower(),
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key in LOG_RECORD_RESERVED or key.startswith("_"):
                continue
            payload[key] = _json_safe(value)
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def configure_logging() -> None:
    log_format = os.environ.get("DELAMAIN_LOG_FORMAT", "json").strip().lower()
    level_name = os.environ.get("DELAMAIN_LOG_LEVEL", "INFO").strip().upper()
    level = getattr(logging, level_name, logging.INFO)

    formatter: logging.Formatter
    if log_format == "plain":
        formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    else:
        formatter = JsonLogFormatter()

    root = logging.getLogger()
    if not root.handlers:
        root.addHandler(logging.StreamHandler())
    root.setLevel(level)
    for handler in root.handlers:
        handler.setFormatter(formatter)
        handler.setLevel(level)

    for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(logger_name)
        logger.setLevel(level)
        for handler in logger.handlers:
            handler.setFormatter(formatter)
            handler.setLevel(level)


def install_request_logging(app: FastAPI) -> None:
    logger = logging.getLogger("delamain_backend.request")

    @app.middleware("http")
    async def _request_logging(
        request: Request,
        call_next: Callable[[Request], Any],
    ) -> Response:
        started = time.perf_counter()
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers.setdefault("x-request-id", request_id)
            return response
        finally:
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            logger.info(
                "http_request",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": status_code,
                    "duration_ms": duration_ms,
                },
            )


def _json_safe(value: Any) -> Any:
    try:
        json.dumps(value)
        return value
    except TypeError:
        return repr(value)
