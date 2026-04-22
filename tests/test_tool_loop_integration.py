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

        rows = client.app.state.db
        assert rows is not None


def _wait_for_run(client: TestClient, run_id: str) -> dict:
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        run = client.get(f"/api/runs/{run_id}").json()
        if run["status"] in {"completed", "failed", "interrupted", "cancelled"}:
            return run
        time.sleep(0.05)
    raise AssertionError("run did not finish")
