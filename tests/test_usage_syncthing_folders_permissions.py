from __future__ import annotations

import json
import sqlite3
import time

from fastapi.testclient import TestClient

from delamain_backend.main import create_app


def test_usage_endpoint_returns_all_provider_shapes(test_config, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_ADMIN_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_ADMIN_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("DELAMAIN_SECRETS_ENV", raising=False)
    monkeypatch.setattr("delamain_backend.subscription_status._CACHE", None)
    monkeypatch.setattr(
        "delamain_backend.subscription_status._run",
        lambda argv: {
            "exit_code": 0,
            "stdout": (
                "2.1.117 (Claude Code)\n"
                '{"loggedIn":true,"authMethod":"claude.ai","apiProvider":"firstParty",'
                '"email":"daniel@example.test","subscriptionType":"pro"}\n'
            )
            if "claude" in argv[-1]
            else "codex-cli 0.122.0\nLogged in using ChatGPT\n",
            "stderr": "",
            "duration_ms": 1,
        },
    )
    app = create_app(test_config)
    with TestClient(app) as client:
        import asyncio

        asyncio.run(
            app.state.db.execute(
                """
                INSERT INTO model_calls(id, run_id, model_route, api_family, status)
                VALUES
                    ('copilot', NULL, 'github_copilot/gpt-5.4-mini', 'responses', 'completed'),
                    ('openrouter', NULL, 'openrouter/deepseek/deepseek-v3.2', 'chat_completions', 'completed'),
                    ('claude', NULL, 'anthropic/claude-sonnet-4.5', 'chat_completions', 'completed'),
                    ('codex', NULL, 'codex/gpt-5.1-codex', 'chat_completions', 'completed')
                """
            )
        )
        payload = client.get("/api/usage").json()

    providers = {item["provider"]: item for item in payload["providers"]}
    assert sorted(providers) == ["claude", "codex", "copilot", "openrouter"]
    assert providers["copilot"]["used"] == 1
    assert providers["copilot"]["limit_or_credits"] == 300
    assert providers["openrouter"]["used"] == 1
    assert providers["openrouter"]["status"] == "not_configured"
    assert providers["claude"]["used"] == 1
    assert providers["claude"]["status"] == "auth_ok_billing_not_configured"
    assert (
        providers["claude"]["details"]["subscription"]["hosts"][0]["subscription_type"]
        == "pro"
    )
    assert providers["codex"]["used"] == 1
    assert payload["subscriptions"]["providers"]["codex"]["aggregate_status"] == "ok"


def test_subscription_status_endpoint_can_refresh(test_config, monkeypatch):
    calls = []

    def fake_run(argv):
        calls.append(argv)
        if "claude" in argv[-1]:
            stdout = (
                "2.1.117 (Claude Code)\n"
                '{"loggedIn":true,"authMethod":"oauth_token","apiProvider":"firstParty"}\n'
            )
        else:
            stdout = "codex-cli 0.122.0\nLogged in using ChatGPT\n"
        return {"exit_code": 0, "stdout": stdout, "stderr": "", "duration_ms": 1}

    monkeypatch.setattr("delamain_backend.subscription_status._run", fake_run)
    monkeypatch.setattr("delamain_backend.subscription_status._CACHE", None)
    app = create_app(test_config)
    with TestClient(app) as client:
        payload = client.get("/api/usage/subscriptions?refresh=true").json()

    assert payload["providers"]["claude"]["aggregate_status"] == "ok"
    assert payload["providers"]["codex"]["aggregate_status"] == "ok"
    assert len(calls) == 4


def test_syncthing_endpoints_read_sync_guard_reports(test_config):
    report_dir = test_config.paths.llm_workspace / "health" / "sync-guard" / "hosts" / "serrano"
    report_dir.mkdir(parents=True)
    conflict = test_config.paths.llm_workspace / "note.sync-conflict-20260422-120000-ABC.md"
    conflict.write_text("conflict", encoding="utf-8")
    (report_dir / "latest.json").write_text(
        json.dumps(
            {
                "health": {
                    "host": "serrano",
                    "timestamp": "2026-04-22T12:00:00",
                    "conflict_count": 1,
                    "junk_count": 0,
                    "syncthing": {
                        "available": True,
                        "folders": {
                            "llm-workspace": {
                                "state": "idle",
                                "needTotalItems": 0,
                                "needBytes": 0,
                                "errors": 0,
                                "pullErrors": 0,
                                "globalTotalItems": 10,
                                "localTotalItems": 10,
                            }
                        },
                        "connections": {
                            "device": {
                                "connected": True,
                                "address": "tcp://example",
                                "clientVersion": "v1",
                                "paused": False,
                                "at": "2026-04-22T12:00:00Z",
                            }
                        },
                    },
                },
                "resolver": {
                    "review_items": [
                        {
                            "conflict": str(conflict),
                            "canonical": str(test_config.paths.llm_workspace / "note.md"),
                            "reason": "manual text merge required",
                            "review_dir": str(test_config.paths.llm_workspace / "review"),
                        }
                    ]
                },
            }
        ),
        encoding="utf-8",
    )
    app = create_app(test_config)
    with TestClient(app) as client:
        summary = client.get("/api/syncthing/summary").json()
        conflicts = client.get("/api/syncthing/conflicts").json()

    serrano = next(device for device in summary["devices"] if device["host"] == "serrano")
    assert serrano["status"] == "degraded"
    assert serrano["folders"][0]["folder_id"] == "llm-workspace"
    assert conflicts["conflicts"][0]["path"] == str(conflict)
    assert conflicts["conflicts"][0]["folder_id"] == "llm-workspace"


def test_syncthing_conflict_resolution_keep_both_writes_backup(test_config):
    canonical = test_config.paths.llm_workspace / "note.md"
    conflict = test_config.paths.llm_workspace / "note.sync-conflict-20260422-120000-ABC.md"
    canonical.write_text("canonical", encoding="utf-8")
    conflict.write_text("conflict", encoding="utf-8")
    app = create_app(test_config)
    with TestClient(app) as client:
        result = client.post(
            "/api/syncthing/conflicts/resolve",
            json={"path": str(conflict), "action": "keep_both", "note": "test"},
        )

    assert result.status_code == 200
    payload = result.json()
    assert payload["status"] == "resolved"
    assert canonical.read_text(encoding="utf-8") == "canonical"
    kept = test_config.paths.llm_workspace / "note.conflict-copy.md"
    assert kept.read_text(encoding="utf-8") == "conflict"
    assert not conflict.exists()
    assert (test_config.database.path.parent / "syncthing-conflict-resolution-backups").exists()


def test_conversation_folders_crud_and_conversation_assignment(test_config):
    app = create_app(test_config)
    with TestClient(app) as client:
        created = client.post("/api/folders", json={"name": "Work"}).json()
        folder_id = created["id"]
        assert client.get("/api/folders").json()[0]["name"] == "Work"
        renamed = client.patch(f"/api/folders/{folder_id}", json={"name": "School"}).json()
        assert renamed["name"] == "School"
        conversation = client.post(
            "/api/conversations",
            json={"title": "Foldered", "folder_id": folder_id},
        ).json()
        assert conversation["folder_id"] == folder_id
        moved = client.patch(
            f"/api/conversations/{conversation['id']}",
            json={"folder_id": None},
        ).json()
        assert moved["folder_id"] is None
        assert client.delete(f"/api/folders/{folder_id}").status_code == 204


def test_permission_resolution_endpoint_emits_event(test_config):
    app = create_app(test_config)
    with TestClient(app) as client:
        conversation_id = client.post("/api/conversations", json={}).json()["id"]
        run_id = client.post(
            f"/api/conversations/{conversation_id}/messages",
            json={"content": "hello"},
        ).json()["run_id"]
        _wait_for_run(client, run_id)
        import asyncio

        asyncio.run(
            app.state.db.execute(
                """
                INSERT INTO permissions(
                    id, conversation_id, run_id, kind, summary, details_json
                )
                VALUES ('perm_1', ?, ?, 'tool', 'Approve tool', '{}')
                """,
                (conversation_id, run_id),
            )
        )
        pending = client.get(f"/api/runs/{run_id}/permissions").json()
        assert pending[0]["status"] == "pending"
        resolved = client.post(
            "/api/permissions/perm_1/resolve",
            json={"decision": "approved", "note": "ok", "resolver": "daniel"},
        ).json()
        assert resolved["decision"] == "approved"

    con = sqlite3.connect(test_config.database.path)
    event = con.execute(
        "SELECT payload FROM events WHERE run_id = ? AND type = 'permission.resolved'",
        (run_id,),
    ).fetchone()
    con.close()
    assert json.loads(event[0])["resolver"] == "daniel"


def _wait_for_run(client: TestClient, run_id: str) -> dict:
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        run = client.get(f"/api/runs/{run_id}").json()
        if run["status"] in {"completed", "failed", "interrupted", "cancelled"}:
            return run
        time.sleep(0.05)
    raise AssertionError("run did not finish")
