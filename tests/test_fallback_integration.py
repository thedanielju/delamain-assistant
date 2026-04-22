import time
import sqlite3

from fastapi.testclient import TestClient

from delamain_backend.agent.router import api_family_for_route
from delamain_backend.main import create_app


class FailsFirstModelClient:
    def __init__(self):
        self.routes: list[tuple[str, str]] = []

    async def complete(self, *, model_route, messages, tools=None):
        self.routes.append((model_route, api_family_for_route(model_route)))
        if len(self.routes) == 1:
            raise RuntimeError("first route failed")
        return {
            "id": "fake_ok",
            "model": model_route,
            "api_family": api_family_for_route(model_route),
            "text": "fallback ok",
            "tool_calls": [],
            "usage": {
                "model": model_route,
                "provider": model_route.split("/", 1)[0],
                "input_tokens": 1,
                "output_tokens": 2,
                "premium_units": None,
                "estimated_cost_usd": None,
            },
            "raw": {},
        }


def test_model_fallback_is_explicit_and_recorded(test_config):
    model_client = FailsFirstModelClient()
    app = create_app(test_config, model_client=model_client)
    with TestClient(app) as client:
        conversation_id = client.post("/api/conversations", json={}).json()["id"]
        run_id = client.post(
            f"/api/conversations/{conversation_id}/messages",
            json={"content": "trigger fallback"},
        ).json()["run_id"]
        run = _wait_for_run(client, run_id)
        assert run["status"] == "completed"
        assert model_client.routes == [
            ("github_copilot/gpt-5.4-mini", "responses"),
            ("github_copilot/gpt-5-mini", "chat_completions"),
        ]

        con = sqlite3.connect(test_config.database.path)
        con.row_factory = sqlite3.Row
        model_calls = [
            dict(row)
            for row in con.execute(
                "SELECT * FROM model_calls WHERE run_id = ? ORDER BY created_at",
                (run_id,),
            )
        ]
        assert [row["status"] for row in model_calls] == ["failed", "completed"]
        assert model_calls[1]["fallback_from"] == "github_copilot/gpt-5.4-mini"

        events = [
            dict(row)
            for row in con.execute(
                "SELECT * FROM events WHERE run_id = ? AND type = 'audit'", (run_id,)
            )
        ]
        assert any("model.fallback" in row["payload"] for row in events)


def _wait_for_run(client: TestClient, run_id: str) -> dict:
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        run = client.get(f"/api/runs/{run_id}").json()
        if run["status"] in {"completed", "failed", "interrupted", "cancelled"}:
            return run
        time.sleep(0.05)
    raise AssertionError("run did not finish")
