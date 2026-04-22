import json
import sqlite3
import time
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from delamain_backend.config import PathsConfig
from delamain_backend.errors import SensitiveLocked, ToolPolicyDenied
from delamain_backend.main import create_app
from delamain_backend.tools import ToolExecutionContext, default_tool_registry


class ToolCallModelClient:
    def __init__(self, tool_call):
        self.tool_call = tool_call
        self.calls = 0

    async def complete(self, *, model_route, messages, tools=None):
        self.calls += 1
        if self.calls == 1:
            return {
                "id": "tool_request",
                "model": model_route,
                "api_family": "responses",
                "text": "",
                "tool_calls": [self.tool_call],
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


@pytest.fixture
def m4_config(test_config, tmp_path):
    vault = tmp_path / "Vault"
    workspace = tmp_path / "llm-workspace"
    sensitive = tmp_path / "Sensitive"
    vault.mkdir(exist_ok=True)
    workspace.mkdir(exist_ok=True)
    sensitive.mkdir(exist_ok=True)
    return replace(
        test_config,
        paths=PathsConfig(vault=vault, sensitive=sensitive, llm_workspace=workspace),
    )


async def test_read_text_file_tool_reads_allowed_text(m4_config):
    note = m4_config.paths.vault / "note.md"
    note.write_text("hello vault", encoding="utf-8")
    result = await default_tool_registry(m4_config).execute(
        "read_text_file",
        {"path": str(note)},
        ToolExecutionContext(sensitive_unlocked=False),
    )
    assert result["stdout"] == "hello vault"


async def test_read_text_file_reads_only_output_window(m4_config):
    note = m4_config.paths.vault / "large.md"
    note.write_text("abcdef", encoding="utf-8")
    limited = replace(m4_config, tools=replace(m4_config.tools, output_limit_bytes=3))
    result = await default_tool_registry(limited).execute(
        "read_text_file",
        {"path": str(note)},
        ToolExecutionContext(sensitive_unlocked=False),
    )
    assert result["stdout"] == "abc"
    assert result["byte_count"] == 6
    assert result["truncated"] is True


async def test_read_text_file_tool_blocks_sensitive_when_locked(m4_config):
    secret = m4_config.paths.sensitive / "harmless.md"
    secret.write_text("fixture secret", encoding="utf-8")
    with pytest.raises(SensitiveLocked):
        await default_tool_registry(m4_config).execute(
            "read_text_file",
            {"path": str(secret)},
            ToolExecutionContext(sensitive_unlocked=False),
        )


async def test_list_directory_omits_restricted_entries(m4_config):
    (m4_config.paths.vault / "safe.md").write_text("safe", encoding="utf-8")
    (m4_config.paths.vault / ".env").write_text("blocked", encoding="utf-8")
    result = await default_tool_registry(m4_config).execute(
        "list_directory",
        {"path": str(m4_config.paths.vault)},
        ToolExecutionContext(sensitive_unlocked=False),
    )
    payload = json.loads(result["stdout"])
    assert [entry["name"] for entry in payload["entries"]] == ["safe.md"]
    assert payload["omitted_restricted"] == 1


async def test_list_directory_blocks_symlink_escape(m4_config):
    outside = m4_config.paths.vault.parent / "outside-secret.txt"
    outside.write_text("outside", encoding="utf-8")
    link = m4_config.paths.vault / "escape-link.txt"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlink creation unavailable in test environment")
    result = await default_tool_registry(m4_config).execute(
        "list_directory",
        {"path": str(m4_config.paths.vault)},
        ToolExecutionContext(sensitive_unlocked=False),
    )
    payload = json.loads(result["stdout"])
    names = [entry["name"] for entry in payload["entries"]]
    assert "escape-link.txt" not in names
    assert payload["omitted_restricted"] >= 1


async def test_search_vault_finds_text_and_skips_restricted(m4_config):
    (m4_config.paths.vault / "safe.md").write_text("needle here", encoding="utf-8")
    (m4_config.paths.vault / ".env").write_text("needle secret", encoding="utf-8")
    result = await default_tool_registry(m4_config).execute(
        "search_vault",
        {"query": "needle"},
        ToolExecutionContext(sensitive_unlocked=False),
    )
    payload = json.loads(result["stdout"])
    assert len(payload["results"]) == 1
    assert payload["results"][0]["path"].endswith("safe.md")


async def test_search_vault_uses_vault_index_when_available(m4_config):
    safe = m4_config.paths.vault / "safe.md"
    safe.write_text("no direct match needed", encoding="utf-8")
    env_file = m4_config.paths.vault / ".env"
    env_file.write_text("needle secret", encoding="utf-8")
    helper = m4_config.paths.llm_workspace / "bin" / "delamain-vault-index"
    helper.parent.mkdir(parents=True, exist_ok=True)
    helper.write_text(
        "#!/usr/bin/env python3\n"
        "import json\n"
        "print(json.dumps({'matches': ["
        "{'kind': 'note', 'value': 'safe.md'},"
        "{'kind': 'note', 'value': '.env'},"
        "{'kind': 'heading', 'value': {'file': 'safe.md', 'heading': 'Needle', 'level': 2, 'anchor': 'needle'}}"
        "]}))\n",
        encoding="utf-8",
    )
    helper.chmod(0o755)
    result = await default_tool_registry(m4_config).execute(
        "search_vault",
        {"query": "needle", "limit": 10},
        ToolExecutionContext(sensitive_unlocked=False),
    )
    payload = json.loads(result["stdout"])
    assert payload["source"] == "vault-index"
    assert len(payload["results"]) == 2
    assert all(not item["path"].endswith(".env") for item in payload["results"])


async def test_search_vault_ignores_symlink_escape(m4_config):
    safe = m4_config.paths.vault / "safe.md"
    safe.write_text("needle safe", encoding="utf-8")
    outside = m4_config.paths.vault.parent / "outside-secret.md"
    outside.write_text("needle outside", encoding="utf-8")
    link = m4_config.paths.vault / "escape.md"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlink creation unavailable in test environment")
    result = await default_tool_registry(m4_config).execute(
        "search_vault",
        {"query": "needle"},
        ToolExecutionContext(sensitive_unlocked=False),
    )
    payload = json.loads(result["stdout"])
    assert len(payload["results"]) == 1
    assert payload["results"][0]["path"].endswith("safe.md")


def test_tool_loop_blocks_sensitive_until_conversation_unlock(m4_config):
    secret = m4_config.paths.sensitive / "harmless.md"
    secret.write_text("fixture secret", encoding="utf-8")
    call = {
        "id": "call_sensitive",
        "name": "read_text_file",
        "arguments": {"path": str(secret)},
        "source_api_family": "responses",
        "raw": {},
    }
    app = create_app(m4_config, model_client=ToolCallModelClient(call))
    with TestClient(app) as client:
        conversation_id = client.post("/api/conversations", json={}).json()["id"]
        run_id = client.post(
            f"/api/conversations/{conversation_id}/messages",
            json={"content": "read sensitive"},
        ).json()["run_id"]
        run = _wait_for_run(client, run_id)
        assert run["status"] == "failed"
        assert run["error_code"] == "SENSITIVE_LOCKED"
        events = _audit_payloads(m4_config.database.path, run_id)
        assert any(
            event["action"] == "sensitive.access" and event["status"] == "denied"
            for event in events
        )


def test_tool_loop_allows_sensitive_only_after_unlock_endpoint(m4_config):
    secret = m4_config.paths.sensitive / "harmless.md"
    secret.write_text("fixture secret", encoding="utf-8")
    call = {
        "id": "call_sensitive",
        "name": "read_text_file",
        "arguments": {"path": str(secret)},
        "source_api_family": "responses",
        "raw": {},
    }
    app = create_app(m4_config, model_client=ToolCallModelClient(call))
    with TestClient(app) as client:
        conversation_id = client.post("/api/conversations", json={}).json()["id"]
        locked = client.get(f"/api/conversations/{conversation_id}").json()
        assert locked["sensitive_unlocked"] is False
        unlocked = client.post(f"/api/conversations/{conversation_id}/sensitive/unlock")
        assert unlocked.status_code == 200
        assert unlocked.json()["sensitive_unlocked"] is True
        run_id = client.post(
            f"/api/conversations/{conversation_id}/messages",
            json={"content": "read sensitive"},
        ).json()["run_id"]
        run = _wait_for_run(client, run_id)
        assert run["status"] == "completed"
        con = sqlite3.connect(m4_config.database.path)
        content = con.execute(
            "SELECT content FROM messages WHERE run_id = ? AND role = 'tool'", (run_id,)
        ).fetchone()[0]
        assert "fixture secret" in content
        events = _audit_payloads(m4_config.database.path, run_id)
        assert any(
            event["action"] == "sensitive.access" and event["status"] == "allowed"
            for event in events
        )


def test_lock_endpoint_relocks_sensitive_for_later_tool_calls(m4_config):
    secret = m4_config.paths.sensitive / "harmless.md"
    secret.write_text("fixture secret", encoding="utf-8")
    call = {
        "id": "call_sensitive",
        "name": "read_text_file",
        "arguments": {"path": str(secret)},
        "source_api_family": "responses",
        "raw": {},
    }
    app = create_app(m4_config, model_client=ToolCallModelClient(call))
    with TestClient(app) as client:
        conversation_id = client.post("/api/conversations", json={}).json()["id"]
        client.post(f"/api/conversations/{conversation_id}/sensitive/unlock")
        locked = client.post(f"/api/conversations/{conversation_id}/sensitive/lock")
        assert locked.status_code == 200
        assert locked.json()["sensitive_unlocked"] is False
        run_id = client.post(
            f"/api/conversations/{conversation_id}/messages",
            json={"content": "read sensitive after relock"},
        ).json()["run_id"]
        run = _wait_for_run(client, run_id)
        assert run["status"] == "failed"
        assert run["error_code"] == "SENSITIVE_LOCKED"


def test_model_cannot_unlock_sensitive_by_tool_call(m4_config):
    assert default_tool_registry(m4_config).has_tool("sensitive_unlock") is False
    call = {
        "id": "call_unlock",
        "name": "sensitive_unlock",
        "arguments": {},
        "source_api_family": "responses",
        "raw": {},
    }
    app = create_app(m4_config, model_client=ToolCallModelClient(call))
    with TestClient(app) as client:
        conversation_id = client.post("/api/conversations", json={}).json()["id"]
        run_id = client.post(
            f"/api/conversations/{conversation_id}/messages",
            json={"content": "unlock sensitive"},
        ).json()["run_id"]
        run = _wait_for_run(client, run_id)
        assert run["status"] == "failed"
        assert run["error_code"] == "TOOL_POLICY_DENIED"
        conversation = client.get(f"/api/conversations/{conversation_id}").json()
        assert conversation["sensitive_unlocked"] is False


async def test_read_text_file_blocks_restricted_file(m4_config):
    env_file = m4_config.paths.vault / ".env"
    env_file.write_text("TOKEN=hidden", encoding="utf-8")
    with pytest.raises(ToolPolicyDenied):
        await default_tool_registry(m4_config).execute(
            "read_text_file",
            {"path": str(env_file)},
            ToolExecutionContext(sensitive_unlocked=False),
        )


async def test_patch_text_file_replaces_exactly_once_and_backs_up(m4_config):
    note = m4_config.paths.vault / "note.md"
    note.write_text("hello old text", encoding="utf-8")
    result = await default_tool_registry(m4_config).execute(
        "patch_text_file",
        {"path": str(note), "old_text": "old", "new_text": "new"},
        ToolExecutionContext(sensitive_unlocked=False),
    )
    assert result["status"] == "success"
    assert note.read_text(encoding="utf-8") == "hello new text"
    payload = json.loads(result["stdout"])
    assert payload["backup_path"]
    assert "old_sha256" in payload


async def test_patch_text_file_writes_sensitive_when_unlocked(m4_config):
    secret = m4_config.paths.sensitive / "note.md"
    secret.write_text("old", encoding="utf-8")
    result = await default_tool_registry(m4_config).execute(
        "patch_text_file",
        {"path": str(secret), "old_text": "old", "new_text": "new"},
        ToolExecutionContext(sensitive_unlocked=True),
    )
    assert result["status"] == "success"
    assert result["root"] == "sensitive"
    assert secret.read_text(encoding="utf-8") == "new"


async def test_patch_text_file_blocks_sensitive_when_locked(m4_config):
    secret = m4_config.paths.sensitive / "note.md"
    secret.write_text("old", encoding="utf-8")
    with pytest.raises(SensitiveLocked):
        await default_tool_registry(m4_config).execute(
            "patch_text_file",
            {"path": str(secret), "old_text": "old", "new_text": "new"},
            ToolExecutionContext(sensitive_unlocked=False),
        )


async def test_patch_text_file_requires_single_preimage_match(m4_config):
    note = m4_config.paths.vault / "note.md"
    note.write_text("same same", encoding="utf-8")
    with pytest.raises(ToolPolicyDenied, match="exactly once"):
        await default_tool_registry(m4_config).execute(
            "patch_text_file",
            {"path": str(note), "old_text": "same", "new_text": "new"},
            ToolExecutionContext(sensitive_unlocked=False),
        )


async def test_run_shell_executes_argv_with_allowed_cwd(m4_config):
    result = await default_tool_registry(m4_config).execute(
        "run_shell",
        {
            "argv": ["/usr/bin/printf", "ok"],
            "cwd": str(m4_config.paths.llm_workspace),
        },
        ToolExecutionContext(sensitive_unlocked=False),
    )
    assert result["status"] == "success"
    assert result["stdout"] == "ok"


async def test_run_shell_denies_sensitive_cwd_and_argv(m4_config):
    with pytest.raises((ToolPolicyDenied, SensitiveLocked)):
        await default_tool_registry(m4_config).execute(
            "run_shell",
            {"argv": ["/bin/echo", "ok"], "cwd": str(m4_config.paths.sensitive)},
            ToolExecutionContext(sensitive_unlocked=False),
        )
    with pytest.raises(ToolPolicyDenied, match="Sensitive paths"):
        await default_tool_registry(m4_config).execute(
            "run_shell",
            {
                "argv": ["/bin/echo", str(m4_config.paths.sensitive / "note.md")],
                "cwd": str(m4_config.paths.llm_workspace),
            },
            ToolExecutionContext(sensitive_unlocked=False),
        )


async def test_run_shell_denies_shell_command_strings(m4_config):
    with pytest.raises(ToolPolicyDenied, match="shell -c"):
        await default_tool_registry(m4_config).execute(
            "run_shell",
            {
                "argv": ["/bin/bash", "-lc", "echo unsafe"],
                "cwd": str(m4_config.paths.llm_workspace),
            },
            ToolExecutionContext(sensitive_unlocked=False),
        )


def _wait_for_run(client: TestClient, run_id: str) -> dict:
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        run = client.get(f"/api/runs/{run_id}").json()
        if run["status"] in {"completed", "failed", "interrupted", "cancelled"}:
            return run
        time.sleep(0.05)
    raise AssertionError("run did not finish")


def _audit_payloads(db_path, run_id: str) -> list[dict]:
    con = sqlite3.connect(db_path)
    rows = con.execute(
        "SELECT payload FROM events WHERE run_id = ? AND type = 'audit' ORDER BY id",
        (run_id,),
    ).fetchall()
    con.close()
    return [json.loads(row[0]) for row in rows]
