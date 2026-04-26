import json
import sqlite3
import time

from fastapi.testclient import TestClient

from delamain_backend.main import create_app


def test_health_and_prompt_lifecycle(test_config):
    app = create_app(test_config)
    with TestClient(app) as client:
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json()["sqlite"]["ok"] is True
        assert health.json()["sqlite"]["wal_verified"] is True
        assert health.json()["sqlite"]["write"]["busy_timeout_ms"] == 5000
        assert health.json()["config"]["model_calls_enabled"] is False
        assert "system" in health.json()
        assert health.json()["system"]["delamain_backend"]["pid"] > 0

        created = client.post("/api/conversations", json={"title": "Test"})
        assert created.status_code == 201
        conversation_id = created.json()["id"]

        submitted = client.post(
            f"/api/conversations/{conversation_id}/messages",
            json={"content": "hello"},
        )
        assert submitted.status_code == 202
        run_id = submitted.json()["run_id"]

        run = _wait_for_run(client, run_id)
        assert run["status"] == "completed"

        messages = client.get(f"/api/conversations/{conversation_id}/messages").json()
        assert [message["role"] for message in messages] == ["user", "assistant"]
        assert "DELAMAIN backend stub response" in messages[1]["content"]

        events = client.get(f"/api/conversations/{conversation_id}/runs").json()
        assert events[0]["id"] == run_id

        retry = client.post(f"/api/runs/{run_id}/retry")
        assert retry.status_code == 202
        retried = _wait_for_run(client, retry.json()["run_id"])
        assert retried["status"] == "completed"


def test_sensitive_lock_unlock_endpoints_are_explicit_and_audited(test_config):
    app = create_app(test_config)
    with TestClient(app) as client:
        created = client.post(
            "/api/conversations",
            json={"title": "Sensitive", "sensitive_unlocked": True},
        )
        assert created.status_code == 201
        conversation_id = created.json()["id"]
        assert created.json()["sensitive_unlocked"] is False

        unlocked = client.post(f"/api/conversations/{conversation_id}/sensitive/unlock")
        assert unlocked.status_code == 200
        assert unlocked.json()["sensitive_unlocked"] is True
        fetched = client.get(f"/api/conversations/{conversation_id}").json()
        assert fetched["sensitive_unlocked"] is True

        locked = client.post(f"/api/conversations/{conversation_id}/sensitive/lock")
        assert locked.status_code == 200
        assert locked.json()["sensitive_unlocked"] is False
        fetched = client.get(f"/api/conversations/{conversation_id}").json()
        assert fetched["sensitive_unlocked"] is False

    con = sqlite3.connect(test_config.database.path)
    rows = con.execute(
        """
        SELECT payload
        FROM events
        WHERE conversation_id = ? AND type = 'audit'
        ORDER BY id
        """,
        (conversation_id,),
    ).fetchall()
    con.close()
    actions = [json.loads(row[0])["action"] for row in rows]
    assert actions == ["sensitive.unlocked", "sensitive.locked"]


def test_first_prompt_generates_deterministic_title(test_config):
    app = create_app(test_config)
    with TestClient(app) as client:
        conversation_id = client.post("/api/conversations", json={}).json()["id"]
        submitted = client.post(
            f"/api/conversations/{conversation_id}/messages",
            json={"content": "check winpc gpu status and summarize it"},
        )
        assert submitted.status_code == 202
        conversation = client.get(f"/api/conversations/{conversation_id}").json()
        assert conversation["title"] == "check winpc gpu status and summarize it"


def test_persisted_model_default_used_for_new_runs(test_config):
    app = create_app(test_config)
    with TestClient(app) as client:
        assert client.patch(
            "/api/settings",
            json={"values": {"model_default": test_config.models.fallback_high_volume}},
        ).status_code == 200
        conversation_id = client.post("/api/conversations", json={}).json()["id"]
        run_id = client.post(
            f"/api/conversations/{conversation_id}/messages",
            json={"content": "hello"},
        ).json()["run_id"]
        run = client.get(f"/api/runs/{run_id}").json()
        assert run["model_route"] == test_config.models.fallback_high_volume


def _wait_for_run(client: TestClient, run_id: str) -> dict:
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        run = client.get(f"/api/runs/{run_id}").json()
        if run["status"] in {"completed", "failed", "interrupted", "cancelled"}:
            return run
        time.sleep(0.05)
    raise AssertionError("run did not finish")
