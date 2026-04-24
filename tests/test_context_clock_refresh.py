from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from delamain_backend.agent import context as context_module
from delamain_backend.main import create_app


class CapturingModelClient:
    def __init__(self):
        self.messages = None

    async def complete(self, *, model_route, messages, tools=None):
        self.messages = messages
        return {
            "id": "final",
            "model": model_route,
            "api_family": "responses",
            "text": "done",
            "tool_calls": [],
            "usage": None,
            "raw": {},
        }


def test_run_refreshes_clock_block_in_memory_and_emits_audit(test_config, monkeypatch):
    stale_line = "2026-04-23 Thursday · America/New_York (EDT)"
    expected_line = "2026-04-24 Friday · America/New_York (EDT)"
    original_content = (
        "# Delamain\n\n"
        "BEGIN:clock\n"
        f"{stale_line}\n"
        "END:clock\n\n"
        "Keep responses direct.\n"
    )
    test_config.paths.system_context.write_text(original_content, encoding="utf-8")
    heartbeat_dir = test_config.paths.llm_workspace / "health"
    heartbeat_dir.mkdir(parents=True, exist_ok=True)
    (heartbeat_dir / "mac-heartbeat.json").write_text(
        json.dumps(
            {
                "timestamp_utc": "2026-04-24T12:00:00Z",
                "mac_local": "2026-04-24T08:00:00",
                "timezone_abbrev": "EDT",
                "timezone_name": "America/New_York",
                "hostname": "Daniels-MacBook-Pro",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        context_module,
        "_utc_now",
        lambda: datetime(2026, 4, 24, 12, 0, tzinfo=timezone.utc),
    )
    model_client = CapturingModelClient()
    app = create_app(test_config, model_client=model_client)

    with TestClient(app) as client:
        conversation_id = client.post("/api/conversations", json={}).json()["id"]
        run_id = client.post(
            f"/api/conversations/{conversation_id}/messages",
            json={"content": "hello"},
        ).json()["run_id"]
        run = _wait_for_run(client, run_id)
        assert run["status"] == "completed"

    assert model_client.messages is not None
    system_contents = [
        str(message["content"])
        for message in model_client.messages
        if message["role"] == "system"
    ]
    assert any(expected_line in content for content in system_contents)
    assert test_config.paths.system_context.read_text(encoding="utf-8") == original_content

    expected_content = original_content.replace(stale_line, expected_line)
    expected_sha256 = hashlib.sha256(expected_content.encode("utf-8")).hexdigest()

    con = sqlite3.connect(test_config.database.path)
    audit_payloads = [
        json.loads(row[0])
        for row in con.execute(
            "SELECT payload FROM events WHERE conversation_id = ? AND type = 'audit' ORDER BY id",
            (conversation_id,),
        )
    ]
    context_load = con.execute(
        "SELECT sha256, byte_count FROM context_loads WHERE run_id = ? AND mode = 'system_context'",
        (run_id,),
    ).fetchone()
    con.close()

    refreshed = next(
        payload for payload in audit_payloads if payload["action"] == "context.clock_refreshed"
    )
    assert refreshed["previous_clock"] == stale_line
    assert refreshed["clock"] == expected_line
    assert context_load == (expected_sha256, len(expected_content.encode("utf-8")))


def test_run_skips_clock_audit_when_block_already_current(test_config, monkeypatch):
    current_line = "2026-04-24 Friday · America/New_York (EDT)"
    test_config.paths.system_context.write_text(
        "BEGIN:clock\n"
        f"{current_line}\n"
        "END:clock\n",
        encoding="utf-8",
    )
    heartbeat_dir = test_config.paths.llm_workspace / "health"
    heartbeat_dir.mkdir(parents=True, exist_ok=True)
    (heartbeat_dir / "mac-heartbeat.json").write_text(
        json.dumps(
            {
                "timestamp_utc": "2026-04-24T12:00:00Z",
                "mac_local": "2026-04-24T08:00:00",
                "timezone_abbrev": "EDT",
                "timezone_name": "America/New_York",
                "hostname": "Daniels-MacBook-Pro",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        context_module,
        "_utc_now",
        lambda: datetime(2026, 4, 24, 12, 0, tzinfo=timezone.utc),
    )
    model_client = CapturingModelClient()
    app = create_app(test_config, model_client=model_client)

    with TestClient(app) as client:
        conversation_id = client.post("/api/conversations", json={}).json()["id"]
        run_id = client.post(
            f"/api/conversations/{conversation_id}/messages",
            json={"content": "hello"},
        ).json()["run_id"]
        run = _wait_for_run(client, run_id)
        assert run["status"] == "completed"

    con = sqlite3.connect(test_config.database.path)
    actions = [
        json.loads(row[0])["action"]
        for row in con.execute(
            "SELECT payload FROM events WHERE conversation_id = ? AND type = 'audit' ORDER BY id",
            (conversation_id,),
        )
    ]
    con.close()
    assert "context.clock_refreshed" not in actions
    assert any(
        current_line in str(message["content"])
        for message in model_client.messages
        if message["role"] == "system"
    )


def _wait_for_run(client: TestClient, run_id: str) -> dict:
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        run = client.get(f"/api/runs/{run_id}").json()
        if run["status"] in {"completed", "failed", "interrupted", "cancelled"}:
            return run
        time.sleep(0.05)
    raise AssertionError("run did not finish")
