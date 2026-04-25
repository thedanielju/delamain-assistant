from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from dataclasses import replace
from datetime import UTC, datetime

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


class MetadataModelClient:
    async def complete(self, *, model_route, messages, tools=None):
        return {
            "id": "metadata_ok",
            "model": model_route,
            "api_family": api_family_for_route(model_route),
            "text": "metadata ok",
            "tool_calls": [],
            "usage": {
                "model": model_route,
                "input_tokens": 7,
                "output_tokens": 3,
                "premium_units": 2,
                "usage_source": "provider_headers",
                "usage_estimated": False,
                "premium_request_source": "provider_headers",
                "estimated_cost_usd": 0.01,
            },
            "provider_usage": {"input_tokens": 7, "output_tokens": 3},
            "response_headers": {"x-copilot-premium-requests": "2"},
            "raw": {},
        }


_TEST_LOOP: asyncio.AbstractEventLoop | None = None


def _event_loop() -> asyncio.AbstractEventLoop:
    global _TEST_LOOP
    if _TEST_LOOP is None or _TEST_LOOP.is_closed():
        _TEST_LOOP = asyncio.new_event_loop()
        asyncio.set_event_loop(_TEST_LOOP)
    return _TEST_LOOP


def test_copilot_budget_counts_completed_copilot_model_calls(test_config):
    app = create_app(test_config)
    with TestClient(app) as client:
        assert client.get("/api/settings/budget").json()["copilot_budget"][
            "used_premium_requests"
        ] == 0
        loop = _event_loop()
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


def test_copilot_budget_aggregates_authoritative_and_estimated_counts(test_config):
    app = create_app(test_config)
    with TestClient(app) as client:

        loop = _event_loop()
        loop.run_until_complete(
            app.state.db.execute(
                """
                INSERT INTO model_calls(
                    id, run_id, model_route, api_family, status,
                    usage_json, usage_source, usage_estimated, premium_request_count
                )
                VALUES
                    (
                        'mc_authoritative',
                        NULL,
                        'github_copilot/gpt-5.4-mini',
                        'responses',
                        'completed',
                        ?,
                        'provider_body',
                        0,
                        2
                    ),
                    (
                        'mc_estimated',
                        NULL,
                        'github_copilot/gpt-5-mini',
                        'chat_completions',
                        'completed',
                        ?,
                        'provider_body',
                        1,
                        1
                    ),
                    (
                        'mc_legacy',
                        NULL,
                        'github_copilot/claude-haiku-4.5',
                        'chat_completions',
                        'completed',
                        NULL,
                        NULL,
                        NULL,
                        NULL
                    )
                """,
                (
                    json.dumps({"premium_units": 2}),
                    json.dumps({"premium_units": 1}),
                ),
            )
        )

        budget = client.get("/api/settings/budget").json()["copilot_budget"]

    assert budget["used_premium_requests"] == 4
    assert budget["tracked_model_calls"] == 3
    assert budget["authoritative_premium_requests"] == 2
    assert budget["estimated_premium_requests"] == 2
    assert budget["usage_estimated"] is True
    assert budget["usage_source"] == "mixed"


def test_copilot_budget_reports_last_observed_timestamp(test_config, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_ADMIN_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_ADMIN_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("delamain_backend.subscription_status._CACHE", None)
    monkeypatch.setattr(
        "delamain_backend.subscription_status._run",
        lambda argv: {"exit_code": 1, "stdout": "", "stderr": "", "duration_ms": 1},
    )
    current_month = datetime.now(UTC).strftime("%Y-%m")
    older = f"{current_month}-02T12:00:00.000Z"
    newest = f"{current_month}-03T12:00:00.000Z"
    ignored_failed = f"{current_month}-04T12:00:00.000Z"
    ignored_provider = f"{current_month}-05T12:00:00.000Z"
    app = create_app(test_config)
    with TestClient(app) as client:

        loop = _event_loop()
        loop.run_until_complete(
            app.state.db.execute(
                """
                INSERT INTO model_calls(
                    id, run_id, model_route, api_family, status, created_at, completed_at
                )
                VALUES
                    ('mc_old', NULL, 'github_copilot/gpt-5.4-mini', 'responses', 'completed', ?, NULL),
                    ('mc_new', NULL, 'github_copilot/gpt-5-mini', 'chat_completions', 'completed', ?, ?),
                    ('mc_failed', NULL, 'github_copilot/gpt-5-mini', 'chat_completions', 'failed', ?, ?),
                    ('mc_openrouter', NULL, 'openrouter/deepseek/deepseek-v3.2', 'chat_completions', 'completed', ?, ?)
                """,
                (
                    older,
                    older,
                    newest,
                    older,
                    ignored_failed,
                    older,
                    ignored_provider,
                ),
            )
        )

        budget = client.get("/api/settings/budget").json()["copilot_budget"]
        health_budget = client.get("/api/health").json()["budget"]
        usage = client.get("/api/usage").json()

    copilot_usage = {
        item["provider"]: item for item in usage["providers"]
    }["copilot"]
    assert budget["last_observed_at"] == newest
    assert health_budget["last_observed_at"] == newest
    assert copilot_usage["details"]["last_observed_at"] == newest


def test_completed_model_call_persists_usage_metadata(test_config):
    app = create_app(test_config, model_client=MetadataModelClient())
    with TestClient(app) as client:
        conversation_id = client.post("/api/conversations", json={}).json()["id"]
        run_id = client.post(
            f"/api/conversations/{conversation_id}/messages",
            json={"content": "persist metadata"},
        ).json()["run_id"]
        run = _wait_for_run(client, run_id)

    assert run["status"] == "completed"
    con = sqlite3.connect(test_config.database.path)
    con.row_factory = sqlite3.Row
    row = con.execute(
        """
        SELECT
            usage_source,
            usage_estimated,
            input_tokens,
            output_tokens,
            premium_request_count,
            estimated_cost_usd,
            provider_usage_json,
            response_headers_json
        FROM model_calls
        WHERE run_id = ?
        """,
        (run_id,),
    ).fetchone()
    con.close()

    assert row["usage_source"] == "provider_headers"
    assert row["usage_estimated"] == 0
    assert row["input_tokens"] == 7
    assert row["output_tokens"] == 3
    assert row["premium_request_count"] == 2
    assert row["estimated_cost_usd"] == 0.01
    assert json.loads(row["provider_usage_json"]) == {
        "input_tokens": 7,
        "output_tokens": 3,
    }
    assert json.loads(row["response_headers_json"]) == {
        "x-copilot-premium-requests": "2"
    }


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

        loop = _event_loop()
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

        loop = _event_loop()
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
