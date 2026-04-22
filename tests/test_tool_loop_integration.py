import json
import sqlite3
import time

from fastapi.testclient import TestClient

from delamain_backend.main import create_app


def test_stub_tool_loop_executes_get_now_and_persists_events(test_config):
    app = create_app(test_config)
    with TestClient(app) as client:
        conversation_id = client.post("/api/conversations", json={}).json()["id"]
        submitted = client.post(
            f"/api/conversations/{conversation_id}/messages",
            json={"content": "what time is it now?"},
        ).json()
        run = _wait_for_run(client, submitted["run_id"])
        assert run["status"] == "completed"

        messages = client.get(f"/api/conversations/{conversation_id}/messages").json()
        assert [message["role"] for message in messages] == ["user", "assistant", "tool"]
        assert "2026-04-17 Friday" in messages[2]["content"]

    con = sqlite3.connect(test_config.database.path)
    con.row_factory = sqlite3.Row
    event_rows = con.execute(
        "SELECT type, payload FROM events WHERE run_id = ? ORDER BY id",
        (submitted["run_id"],),
    ).fetchall()
    con.close()
    assistant_id = run["assistant_message_id"]
    tool_payloads = [
        json.loads(row["payload"])
        for row in event_rows
        if row["type"] in {"tool.started", "tool.output", "tool.finished"}
    ]
    assert tool_payloads
    assert all(payload["assistant_message_id"] == assistant_id for payload in tool_payloads)
    started = next(json.loads(row["payload"]) for row in event_rows if row["type"] == "tool.started")
    output = next(json.loads(row["payload"]) for row in event_rows if row["type"] == "tool.output")
    finished = next(json.loads(row["payload"]) for row in event_rows if row["type"] == "tool.finished")
    assert started["name"] == started["tool"]
    assert started["args"] == started["arguments"]
    assert output["chunk"] == output["text"]
    assert "stdout" in finished
    assert "stderr" in finished


def _wait_for_run(client: TestClient, run_id: str) -> dict:
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        run = client.get(f"/api/runs/{run_id}").json()
        if run["status"] in {"completed", "failed", "interrupted", "cancelled"}:
            return run
        time.sleep(0.05)
    raise AssertionError("run did not finish")
