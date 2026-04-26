from __future__ import annotations

import json
import logging

from fastapi.testclient import TestClient

from delamain_backend.main import create_app
from delamain_backend.structured_logging import JsonLogFormatter


def test_json_log_formatter_preserves_structured_fields():
    formatter = JsonLogFormatter()
    record = logging.LogRecord(
        name="delamain.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=12,
        msg="hello",
        args=(),
        exc_info=None,
    )
    record.request_id = "req-1"
    record.duration_ms = 3.25

    payload = json.loads(formatter.format(record))

    assert payload["level"] == "info"
    assert payload["logger"] == "delamain.test"
    assert payload["message"] == "hello"
    assert payload["request_id"] == "req-1"
    assert payload["duration_ms"] == 3.25
    assert payload["ts"].endswith("Z")


def test_request_logging_emits_json_ready_record(test_config, caplog):
    app = create_app(test_config)

    with caplog.at_level(logging.INFO, logger="delamain_backend.request"):
        with TestClient(app) as client:
            response = client.get("/api/health")

    assert response.status_code == 200
    records = [
        record
        for record in caplog.records
        if record.name == "delamain_backend.request" and record.getMessage() == "http_request"
    ]
    assert records
    record = records[-1]
    assert record.method == "GET"
    assert record.path == "/api/health"
    assert record.status_code == 200
    assert record.duration_ms >= 0
    assert response.headers["x-request-id"] == record.request_id
