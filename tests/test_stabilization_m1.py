import asyncio
import json
import sqlite3
import time
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from delamain_backend.agent.runner import new_id
from delamain_backend.config import RuntimeConfig
from delamain_backend.db import Database
from delamain_backend.events import EventBus, stream_events
from delamain_backend.main import create_app


class SlowModelClient:
    def __init__(self, delay: float = 0.35):
        self.delay = delay
        self.calls = 0

    async def complete(self, *, model_route, messages, tools=None):
        self.calls += 1
        await asyncio.sleep(self.delay)
        return {
            "id": f"slow_{self.calls}",
            "model": model_route,
            "api_family": "responses",
            "text": f"slow ok {self.calls}",
            "tool_calls": [],
            "usage": None,
            "raw": {},
        }


class WrongFamilyModelClient:
    async def complete(self, *, model_route, messages, tools=None):
        return {
            "id": "wrong_family",
            "model": model_route,
            "api_family": "chat_completions",
            "text": "",
            "tool_calls": [],
            "usage": None,
            "raw": {},
        }


class ReportedRouteMismatchModelClient:
    async def complete(self, *, model_route, messages, tools=None):
        return {
            "id": "reported_mismatch",
            "model": "github_copilot/auto",
            "api_family": "responses",
            "text": "ok",
            "tool_calls": [],
            "usage": None,
            "raw": {},
        }


def test_startup_marks_running_runs_interrupted(test_config):
    _seed_running_run(test_config.database.path)
    app = create_app(test_config)
    with TestClient(app) as client:
        rows = client.get("/api/conversations/conv_existing/runs").json()
        assert rows[0]["status"] == "interrupted"
        assert rows[0]["error_code"] == "RUN_INTERRUPTED"


def test_startup_marks_waiting_approval_runs_interrupted(test_config):
    _seed_running_run(test_config.database.path, status="waiting_approval")
    app = create_app(test_config)
    with TestClient(app) as client:
        rows = client.get("/api/conversations/conv_existing/runs").json()
        assert rows[0]["status"] == "interrupted"
        assert rows[0]["error_code"] == "RUN_INTERRUPTED_AWAITING_APPROVAL"


def test_one_active_run_per_conversation_queueing(test_config):
    app = create_app(test_config, model_client=SlowModelClient())
    with TestClient(app) as client:
        conversation_id = client.post("/api/conversations", json={}).json()["id"]
        first = client.post(
            f"/api/conversations/{conversation_id}/messages",
            json={"content": "first"},
        ).json()
        second = client.post(
            f"/api/conversations/{conversation_id}/messages",
            json={"content": "second"},
        ).json()
        time.sleep(0.08)
        first_mid = client.get(f"/api/runs/{first['run_id']}").json()
        second_mid = client.get(f"/api/runs/{second['run_id']}").json()
        assert first_mid["status"] == "running"
        assert second_mid["status"] == "queued"

        assert _wait_for_run(client, first["run_id"])["status"] == "completed"
        assert _wait_for_run(client, second["run_id"])["status"] == "completed"


def test_cancel_running_run_persists_cancel_events(test_config):
    app = create_app(test_config, model_client=SlowModelClient(delay=0.5))
    with TestClient(app) as client:
        conversation_id = client.post("/api/conversations", json={}).json()["id"]
        run_id = client.post(
            f"/api/conversations/{conversation_id}/messages",
            json={"content": "cancel me"},
        ).json()["run_id"]
        time.sleep(0.08)
        cancelled = client.post(f"/api/runs/{run_id}/cancel")
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "cancelled"
        assert _wait_for_run(client, run_id)["status"] == "cancelled"

        con = sqlite3.connect(test_config.database.path)
        events = [
            row[0]
            for row in con.execute(
                "SELECT type FROM events WHERE run_id = ? ORDER BY id", (run_id,)
            )
        ]
        assert "error" in events
        assert "run.completed" in events


@pytest.mark.asyncio
async def test_sse_replay_honors_last_event_id(test_config):
    db = Database(test_config.database.path)
    await db.connect()
    await db.migrate()
    bus = EventBus(db)
    await db.execute(
        "INSERT INTO conversations(id, title) VALUES ('conv_sse', 'SSE')"
    )
    first = await db.insert_event(
        conversation_id="conv_sse",
        run_id=None,
        event_type="audit",
        payload={"n": 1},
    )
    second = await db.insert_event(
        conversation_id="conv_sse",
        run_id=None,
        event_type="audit",
        payload={"n": 2},
    )

    request = _DisconnectedRequest({"last-event-id": str(first["id"])})
    chunks = [
        chunk
        async for chunk in stream_events(
            request=request,
            db=db,
            bus=bus,
            conversation_id="conv_sse",
        )
    ]
    await db.close()

    joined = "".join(chunks)
    assert f"id: {first['id']}" not in joined
    assert f"id: {second['id']}" in joined


@pytest.mark.asyncio
async def test_sse_replay_honors_last_event_id_query_param(test_config):
    db = Database(test_config.database.path)
    await db.connect()
    await db.migrate()
    bus = EventBus(db)
    await db.execute(
        "INSERT INTO conversations(id, title) VALUES ('conv_sse_query', 'SSE query')"
    )
    first = await db.insert_event(
        conversation_id="conv_sse_query",
        run_id=None,
        event_type="audit",
        payload={"n": 1},
    )
    second = await db.insert_event(
        conversation_id="conv_sse_query",
        run_id=None,
        event_type="audit",
        payload={"n": 2},
    )

    request = _DisconnectedRequest({}, {"last_event_id": str(first["id"])})
    chunks = [
        chunk
        async for chunk in stream_events(
            request=request,
            db=db,
            bus=bus,
            conversation_id="conv_sse_query",
        )
    ]
    await db.close()

    joined = "".join(chunks)
    assert f"id: {first['id']}" not in joined
    assert f"id: {second['id']}" in joined


@pytest.mark.asyncio
async def test_event_bus_emit_drops_oldest_when_queue_full(test_config):
    db = Database(test_config.database.path)
    await db.connect()
    await db.migrate()
    bus = EventBus(db)
    await db.execute("INSERT INTO conversations(id, title) VALUES ('conv_queue', 'Queue')")
    queue = await bus.subscribe(conversation_id="conv_queue")
    for idx in range(100):
        queue.put_nowait({"id": -(100 - idx), "type": "dummy", "payload": {}})

    emitted = await bus.emit(
        conversation_id="conv_queue",
        run_id=None,
        event_type="audit",
        payload={"ok": True},
    )

    assert queue.qsize() == 100
    ids = [queue.get_nowait()["id"] for _ in range(100)]
    assert -100 not in ids
    assert emitted["id"] in ids
    await bus.unsubscribe(queue, conversation_id="conv_queue")
    await db.close()


@pytest.mark.asyncio
async def test_event_bus_reaps_repeatedly_full_subscriber(test_config):
    db = Database(test_config.database.path)
    await db.connect()
    await db.migrate()
    bus = EventBus(db)
    await db.execute("INSERT INTO conversations(id, title) VALUES ('conv_reap', 'Reap')")
    queue = await bus.subscribe(conversation_id="conv_reap")
    for idx in range(100):
        queue.put_nowait({"id": -idx, "type": "dummy", "payload": {}})

    for idx in range(bus.drop_reap_threshold):
        await bus.emit(
            conversation_id="conv_reap",
            run_id=None,
            event_type="audit",
            payload={"idx": idx},
        )

    assert queue not in bus._conversation_subscribers.get("conv_reap", set())
    await db.close()


def test_run_fails_on_model_api_family_mismatch(test_config):
    strict_config = replace(
        test_config,
        runtime=RuntimeConfig(
            enable_model_calls=test_config.runtime.enable_model_calls,
            disable_model_fallbacks=True,
            model_timeout_seconds=test_config.runtime.model_timeout_seconds,
        ),
    )
    app = create_app(strict_config, model_client=WrongFamilyModelClient())
    with TestClient(app) as client:
        conversation_id = client.post("/api/conversations", json={}).json()["id"]
        run_id = client.post(
            f"/api/conversations/{conversation_id}/messages",
            json={"content": "hello"},
        ).json()["run_id"]
        run = _wait_for_run(client, run_id)
        assert run["status"] == "failed"
        assert run["error_code"] == "RUN_FAILED"
        con = sqlite3.connect(strict_config.database.path)
        row = con.execute(
            "SELECT error_message FROM model_calls WHERE run_id = ? ORDER BY created_at ASC LIMIT 1",
            (run_id,),
        ).fetchone()
        assert row is not None
        assert "unexpected api_family" in row[0]


def test_run_audits_provider_reported_route_mismatch(test_config):
    app = create_app(test_config, model_client=ReportedRouteMismatchModelClient())
    with TestClient(app) as client:
        conversation_id = client.post("/api/conversations", json={}).json()["id"]
        run_id = client.post(
            f"/api/conversations/{conversation_id}/messages",
            json={"content": "hello"},
        ).json()["run_id"]
        run = _wait_for_run(client, run_id)
        assert run["status"] == "completed"
        con = sqlite3.connect(test_config.database.path)
        rows = con.execute(
            "SELECT payload FROM events WHERE run_id = ? AND type = 'audit'",
            (run_id,),
        ).fetchall()
        con.close()
        payloads = [json.loads(row[0]) for row in rows]
        mismatch = [
            payload
            for payload in payloads
            if payload.get("action") == "model.reported_route_mismatch"
        ]
        assert mismatch
        assert mismatch[0]["requested_model_route"] == "github_copilot/gpt-5.4-mini"
        assert mismatch[0]["reported_model"] == "github_copilot/auto"


@pytest.mark.asyncio
async def test_database_execute_transaction_rolls_back_on_error(test_config):
    db = Database(test_config.database.path)
    await db.connect()
    await db.migrate()
    await db.execute("INSERT INTO conversations(id, title) VALUES ('conv_tx', 'Tx')")

    with pytest.raises(sqlite3.IntegrityError):
        await db.execute_transaction(
            [
                (
                    """
                    INSERT INTO messages(id, conversation_id, role, content)
                    VALUES ('msg_tx', 'conv_tx', 'user', 'hello')
                    """,
                    (),
                ),
                (
                    """
                    INSERT INTO messages(id, conversation_id, role, content)
                    VALUES ('msg_tx', 'conv_tx', 'user', 'duplicate')
                    """,
                    (),
                ),
            ]
        )

    rows = await db.fetchall("SELECT * FROM messages WHERE id = 'msg_tx'")
    await db.close()
    assert rows == []


@pytest.mark.asyncio
async def test_database_healthcheck_does_not_accumulate_temp_rows(test_config):
    db = Database(test_config.database.path)
    await db.connect()
    await db.migrate()
    assert await db.healthcheck() is True
    assert await db.healthcheck() is True
    row = await db.fetchone(
        "SELECT name FROM sqlite_temp_master WHERE type = 'table' AND name = 'healthcheck'"
    )
    await db.close()
    assert row is None


def _seed_running_run(path, status="running"):
    con = sqlite3.connect(path)
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS conversations (
            id TEXT PRIMARY KEY,
            title TEXT,
            context_mode TEXT NOT NULL DEFAULT 'normal',
            model_route TEXT,
            incognito_route INTEGER NOT NULL DEFAULT 0,
            sensitive_unlocked INTEGER NOT NULL DEFAULT 0,
            archived INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
            updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS messages (
            id TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL,
            run_id TEXT,
            role TEXT NOT NULL,
            content TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'completed',
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
            updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS runs (
            id TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL,
            user_message_id TEXT NOT NULL,
            assistant_message_id TEXT,
            status TEXT NOT NULL DEFAULT 'queued',
            context_mode TEXT NOT NULL DEFAULT 'normal',
            model_route TEXT NOT NULL,
            incognito_route INTEGER NOT NULL DEFAULT 0,
            error_code TEXT,
            error_message TEXT,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
            started_at TEXT,
            completed_at TEXT
        )
        """
    )
    con.execute("INSERT INTO conversations(id, title) VALUES ('conv_existing', 'Existing')")
    con.execute(
        "INSERT INTO messages(id, conversation_id, role, content) VALUES ('msg_existing', 'conv_existing', 'user', 'hello')"
    )
    con.execute(
        """
        INSERT INTO runs(id, conversation_id, user_message_id, status, context_mode, model_route)
        VALUES ('run_existing', 'conv_existing', 'msg_existing', ?, 'normal', 'github_copilot/gpt-5.4-mini')
        """,
        (status,),
    )
    con.commit()
    con.close()


class _DisconnectedRequest:
    def __init__(self, headers, query_params=None):
        self.headers = headers
        self.query_params = query_params or {}

    async def is_disconnected(self):
        return True


def _wait_for_run(client: TestClient, run_id: str) -> dict:
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        run = client.get(f"/api/runs/{run_id}").json()
        if run["status"] in {"completed", "failed", "interrupted", "cancelled"}:
            return run
        time.sleep(0.05)
    raise AssertionError("run did not finish")
