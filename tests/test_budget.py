from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import replace

from fastapi.testclient import TestClient

from delamain_backend.agent.router import api_family_for_route
from delamain_backend.config import CopilotBudgetConfig
from delamain_backend.main import create_app
from delamain_backend.settings_store import set_setting


class RecordingModelClient:
    def __init__(self):
        self.routes: list[str] = []

    async def complete(self, *, model_route, messages, tools=None):
        self.routes.append(model_route)
        return {
            "id": "recording_ok",
            "model": model_route,
            "api_family": api_family_for_route(model_route),
            "text": "budget fallback ok",
            "tool_calls": [],
            "usage": {"model": model_route, "input_tokens": 1, "output_tokens": 1},
            "raw": {},
        }


def test_copilot_budget_counts_completed_copilot_model_calls(test_config):
    app = create_app(test_config)
    with TestClient(app) as client:
        assert client.get("/api/settings/budget").json()["copilot_budget"][
            "used_premium_requests"
        ] == 0
        import asyncio

        loop = asyncio.get_event_loop()
        loop.run_until_complete(
            app.state.db.execute(
                """
                INSERT INTO model_calls(
                    id, run_id, model_route, api_family, status, usage_json
                )
                VALUES
                    ('mc1', NULL, 'github_copilot/gpt-5.4-mini', 'responses', 'completed', ?),
                    ('mc2', NULL, 'github_copilot/gpt-5-mini', 'chat_completions', 'failed', NULL),
                    ('mc3', NULL, 'openrouter/deepseek/deepseek-v3.2', 'chat_completions', 'completed', NULL)
                """,
                (json.dumps({"input_tokens": 1}),),
            )
        )
        budget = client.get("/api/settings/budget").json()["copilot_budget"]
        assert budget["used_premium_requests"] == 1
        assert budget["monthly_premium_requests"] == 300
        assert budget["status"] == "ok"
        assert budget["hard_override_enabled"] is False
        assert budget["enforced"] is False
        assert client.get("/api/health").json()["budget"]["used_premium_requests"] == 1


def test_copilot_budget_override_setting_is_reported(test_config):
    app = create_app(test_config)
    with TestClient(app) as client:
        assert client.patch(
            "/api/settings",
            json={"values": {"copilot_budget_hard_override_enabled": True}},
        ).status_code == 200
        payload = client.get("/api/settings").json()["settings"]
        assert payload["copilot_budget_hard_override_enabled"] is True
        budget = client.get("/api/settings/budget").json()["copilot_budget"]
        assert budget["hard_override_enabled"] is True


def test_hard_copilot_budget_blocks_copilot_and_falls_back_to_paid(test_config):
    config = replace(
        test_config,
        copilot_budget=CopilotBudgetConfig(
            monthly_premium_requests=1,
            soft_threshold_percent=60,
            hard_threshold_percent=90,
        ),
    )
    model_client = RecordingModelClient()
    app = create_app(config, model_client=model_client)
    with TestClient(app) as client:
        import asyncio

        loop = asyncio.get_event_loop()
        loop.run_until_complete(
            app.state.db.execute(
                """
                INSERT INTO model_calls(
                    id, run_id, model_route, api_family, status, usage_json
                )
                VALUES ('previous', NULL, 'github_copilot/gpt-5.4-mini', 'responses', 'completed', ?)
                """,
                (json.dumps({"input_tokens": 1}),),
            )
        )
        conversation_id = client.post("/api/conversations", json={}).json()["id"]
        run_id = client.post(
            f"/api/conversations/{conversation_id}/messages",
            json={"content": "stay under budget"},
        ).json()["run_id"]

        run = _wait_for_run(client, run_id)
        assert run["status"] == "completed"
        assert model_client.routes == [config.models.paid_fallback]

    con = sqlite3.connect(config.database.path)
    con.row_factory = sqlite3.Row
    rows = [
        dict(row)
        for row in con.execute(
            "SELECT model_route, status FROM model_calls WHERE run_id = ? ORDER BY created_at",
            (run_id,),
        )
    ]
    events = [
        json.loads(row[0])
        for row in con.execute(
            "SELECT payload FROM events WHERE run_id = ? AND type = 'audit'",
            (run_id,),
        )
    ]
    con.close()
    assert [row["status"] for row in rows] == ["blocked", "blocked", "blocked", "completed"]
    assert rows[-1]["model_route"] == config.models.paid_fallback
    assert any(event["action"] == "model.budget_blocked" for event in events)


def test_hard_copilot_budget_override_allows_copilot_route(test_config):
    config = replace(
        test_config,
        copilot_budget=CopilotBudgetConfig(
            monthly_premium_requests=1,
            soft_threshold_percent=60,
            hard_threshold_percent=90,
        ),
    )
    model_client = RecordingModelClient()
    app = create_app(config, model_client=model_client)
    with TestClient(app) as client:
        import asyncio

        loop = asyncio.get_event_loop()
        loop.run_until_complete(
            app.state.db.execute(
                """
                INSERT INTO model_calls(
                    id, run_id, model_route, api_family, status, usage_json
                )
                VALUES ('previous', NULL, 'github_copilot/gpt-5.4-mini', 'responses', 'completed', ?)
                """,
                (json.dumps({"input_tokens": 1}),),
            )
        )
        loop.run_until_complete(
            set_setting(app.state.db, "copilot_budget_hard_override_enabled", True)
        )
        conversation_id = client.post("/api/conversations", json={}).json()["id"]
        run_id = client.post(
            f"/api/conversations/{conversation_id}/messages",
            json={"content": "override budget"},
        ).json()["run_id"]
        run = _wait_for_run(client, run_id)
        assert run["status"] == "completed"
        assert model_client.routes == [config.models.default]


def _wait_for_run(client: TestClient, run_id: str) -> dict:
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        run = client.get(f"/api/runs/{run_id}").json()
        if run["status"] in {"completed", "failed", "interrupted", "cancelled"}:
            return run
        time.sleep(0.05)
    raise AssertionError("run did not finish")
