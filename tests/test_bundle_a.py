from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

from fastapi.testclient import TestClient

from delamain_backend.main import create_app


class ToolCallModelClient:
    def __init__(self, tool_name: str):
        self.tool_name = tool_name
        self.calls = 0

    async def complete(self, *, model_route, messages, tools=None):
        self.calls += 1
        if self.calls == 1:
            return {
                "id": "tool_request",
                "model": model_route,
                "api_family": "responses",
                "text": "",
                "tool_calls": [
                    {
                        "id": "call_tool",
                        "name": self.tool_name,
                        "arguments": {},
                        "source_api_family": "responses",
                        "raw": {},
                    }
                ],
                "usage": None,
                "raw": {},
            }
        return {
            "id": "final",
            "model": model_route,
            "api_family": "responses",
            "text": "done",
            "tool_calls": [],
            "usage": None,
            "raw": {},
        }


def test_action_run_retrieval_and_artifact_ownership(test_config):
    app = create_app(test_config)
    with TestClient(app) as client:
        conversation_id = client.post("/api/conversations", json={}).json()["id"]
        executed = client.post(
            "/api/actions/ref.status",
            json={"conversation_id": conversation_id},
        ).json()
        action_run_id = executed["id"]

        fetched = client.get(f"/api/action-runs/{action_run_id}")
        assert fetched.status_code == 200
        assert fetched.json()["id"] == action_run_id

        stdout = client.get(f"/api/action-runs/{action_run_id}/stdout")
        assert stdout.status_code == 200
        assert "delamain-ref" in stdout.text

        stderr = client.get(f"/api/action-runs/{action_run_id}/stderr")
        assert stderr.status_code == 200

        listed = client.get(f"/api/conversations/{conversation_id}/action-runs")
        assert listed.status_code == 200
        assert listed.json()[0]["id"] == action_run_id

        con = sqlite3.connect(test_config.database.path)
        original_stdout = con.execute(
            "SELECT stdout_path FROM action_runs WHERE id = ?", (action_run_id,)
        ).fetchone()[0]
        alias = Path(original_stdout).with_name("stdout-alias.txt")
        try:
            alias.symlink_to(original_stdout)
        except OSError:
            alias = None
        if alias is not None:
            con.execute(
                "UPDATE action_runs SET stdout_path = ? WHERE id = ?",
                (str(alias), action_run_id),
            )
            con.commit()
            symlinked = client.get(f"/api/action-runs/{action_run_id}/stdout")
            assert symlinked.status_code == 200
            assert "delamain-ref" in symlinked.text

        con.execute(
            "UPDATE action_runs SET stdout_path = ? WHERE id = ?",
            ("/etc/hostname", action_run_id),
        )
        con.commit()
        con.close()
        denied = client.get(f"/api/action-runs/{action_run_id}/stdout")
        assert denied.status_code == 403


def test_settings_persist_and_emit_audit(test_config):
    app = create_app(test_config)
    with TestClient(app) as client:
        initial = client.get("/api/settings")
        assert initial.status_code == 200
        assert initial.json()["settings"]["task_model"] == test_config.models.fallback_cheap

        conversation_id = client.post("/api/conversations", json={}).json()["id"]
        patched = client.patch(
            "/api/settings",
            json={
                "conversation_id": conversation_id,
                "values": {
                    "context_mode": "blank_slate",
                    "title_generation_enabled": False,
                    "task_model": test_config.models.paid_fallback,
                },
            },
        )
        assert patched.status_code == 200
        settings = patched.json()["settings"]
        assert settings["context_mode"] == "blank_slate"
        assert settings["title_generation_enabled"] is False
        assert settings["task_model"] == test_config.models.paid_fallback

    con = sqlite3.connect(test_config.database.path)
    values = dict(con.execute("SELECT key, value FROM settings").fetchall())
    payloads = [
        json.loads(row[0])
        for row in con.execute(
            "SELECT payload FROM events WHERE conversation_id = ? AND type = 'audit'",
            (conversation_id,),
        )
    ]
    con.close()
    assert json.loads(values["context_mode"]) == "blank_slate"
    assert json.loads(values["task_model"]) == test_config.models.paid_fallback
    assert any(payload["action"] == "settings.updated" for payload in payloads)


def test_task_model_setting_rejects_unknown_route(test_config):
    app = create_app(test_config)
    with TestClient(app) as client:
        response = client.patch(
            "/api/settings",
            json={"values": {"task_model": "not/a-real-route"}},
        )
    assert response.status_code == 400
    assert response.json()["detail"] == "Unsupported task_model"


def test_tool_toggle_is_enforced_in_model_tool_loop(test_config):
    app = create_app(test_config, model_client=ToolCallModelClient("get_now"))
    with TestClient(app) as client:
        conversation_id = client.post("/api/conversations", json={}).json()["id"]
        toggle = client.patch(
            "/api/settings/tools/get_now",
            json={"conversation_id": conversation_id, "enabled": False},
        )
        assert toggle.status_code == 200
        run_id = client.post(
            f"/api/conversations/{conversation_id}/messages",
            json={"content": "what time is it?"},
        ).json()["run_id"]
        run = _wait_for_run(client, run_id)
        assert run["status"] == "failed"
        assert run["error_code"] == "TOOL_POLICY_DENIED"


def test_context_read_write_creates_backup_and_audit(test_config):
    app = create_app(test_config)
    with TestClient(app) as client:
        conversation_id = client.post("/api/conversations", json={}).json()["id"]
        current = client.get("/api/context/current?context_mode=normal")
        assert current.status_code == 200
        assert len(current.json()["items"]) == 2

        before = client.get("/api/context/files/system-context")
        assert before.status_code == 200
        assert before.json()["content"] == "system"

        patched = client.patch(
            "/api/context/files/system-context",
            json={"conversation_id": conversation_id, "content": "updated system"},
        )
        assert patched.status_code == 200
        assert patched.json()["content"] == "updated system"

        after = client.get("/api/context/files/system-context")
        assert after.json()["sha256"] == patched.json()["sha256"]

    backup_root = test_config.database.path.parent / "context-backups" / "system-context"
    backups = list(backup_root.glob("*.bak"))
    assert backups
    assert backups[0].read_text(encoding="utf-8") == "system"
    assert str(backup_root).startswith(str(test_config.database.path.parent))

    con = sqlite3.connect(test_config.database.path)
    payloads = [
        json.loads(row[0])
        for row in con.execute(
            "SELECT payload FROM events WHERE conversation_id = ? AND type = 'audit'",
            (conversation_id,),
        )
    ]
    con.close()
    assert any(payload["action"] == "context.file_updated" for payload in payloads)


def test_context_write_missing_file_has_no_backup(test_config):
    continuity = test_config.paths.short_term_continuity
    continuity.unlink()
    app = create_app(test_config)
    with TestClient(app) as client:
        patched = client.patch(
            "/api/context/files/short-term-continuity",
            json={"content": "new continuity"},
        )
        assert patched.status_code == 200
        assert patched.json()["content"] == "new continuity"
    backup_root = test_config.database.path.parent / "context-backups" / "short-term-continuity"
    assert not backup_root.exists()


def _wait_for_run(client: TestClient, run_id: str) -> dict:
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        run = client.get(f"/api/runs/{run_id}").json()
        if run["status"] in {"completed", "failed", "interrupted", "cancelled"}:
            return run
        time.sleep(0.05)
    raise AssertionError("run did not finish")
