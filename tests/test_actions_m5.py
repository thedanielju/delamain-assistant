from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from delamain_backend.actions import ActionRegistry, ActionRunner, ActionSpec
from delamain_backend.db import Database
from delamain_backend.errors import ToolPolicyDenied
from delamain_backend.events import EventBus
from delamain_backend.main import create_app


def test_action_listing_exposes_initial_quick_actions(test_config):
    app = create_app(test_config)
    with TestClient(app) as client:
        response = client.get("/api/actions")
        assert response.status_code == 200
        action_ids = {action["id"] for action in response.json()["actions"]}
    assert {
        "health.backend",
        "health.helpers",
        "ref.status",
        "ref.reconcile_dry_run",
        "vault_index.status",
        "vault_index.build",
        "sync_guard.status",
        "winpc.hostname",
        "winpc.date",
    }.issubset(action_ids)


def test_action_endpoint_runs_successfully_and_audits(test_config):
    app = create_app(test_config)
    with TestClient(app) as client:
        conversation_id = client.post("/api/conversations", json={}).json()["id"]
        response = client.post(
            "/api/actions/ref.status",
            json={"conversation_id": conversation_id},
        )
        assert response.status_code == 202
        result = response.json()
        assert result["status"] == "success"
        assert result["exit_code"] == 0
        assert result["action_id"] == "ref.status"
        assert '"tool":"delamain-ref"' in result["stdout_preview"]
        assert result["stdout_path"].startswith(str(test_config.database.path.parent))
        assert Path(result["stdout_path"]).read_text(encoding="utf-8")

    con = sqlite3.connect(test_config.database.path)
    action_row = con.execute(
        "SELECT status, stdout_path, stderr_path FROM action_runs WHERE id = ?",
        (result["id"],),
    ).fetchone()
    audit_rows = con.execute(
        "SELECT payload FROM events WHERE conversation_id = ? AND type = 'audit' ORDER BY id",
        (conversation_id,),
    ).fetchall()
    con.close()
    assert action_row[0] == "success"
    assert Path(action_row[1]).exists()
    assert Path(action_row[2]).exists()
    audit_actions = [json.loads(row[0])["action"] for row in audit_rows]
    assert audit_actions == ["quick_action.started", "quick_action.completed"]


@pytest.mark.asyncio
async def test_action_runner_denies_sensitive_path_in_argv(test_config):
    runner = await _runner_for_specs(
        test_config,
        [
            ActionSpec(
                id="bad.sensitive",
                label="Bad Sensitive",
                description="Bad action",
                argv=("/bin/echo", str(test_config.paths.sensitive / "x.md")),
                cwd=test_config.paths.llm_workspace,
                timeout_seconds=1,
            )
        ],
    )
    with pytest.raises(ToolPolicyDenied):
        await runner.execute("bad.sensitive")

    rows = await runner.db.fetchall("SELECT status, error_code FROM action_runs")
    await runner.db.close()
    assert rows == [{"status": "denied", "error_code": "TOOL_POLICY_DENIED"}]


@pytest.mark.asyncio
async def test_action_runner_denies_relative_sensitive_path_in_argv(test_config):
    runner = await _runner_for_specs(
        test_config,
        [
            ActionSpec(
                id="bad.relative_sensitive",
                label="Bad Relative Sensitive",
                description="Bad action",
                argv=("/bin/echo", "../Sensitive/file.md"),
                cwd=test_config.paths.vault,
                timeout_seconds=1,
            )
        ],
    )
    with pytest.raises(ToolPolicyDenied):
        await runner.execute("bad.relative_sensitive")

    rows = await runner.db.fetchall("SELECT status, error_code FROM action_runs")
    await runner.db.close()
    assert rows == [{"status": "denied", "error_code": "TOOL_POLICY_DENIED"}]


@pytest.mark.asyncio
async def test_action_runner_denies_flag_sensitive_path_in_argv(test_config):
    runner = await _runner_for_specs(
        test_config,
        [
            ActionSpec(
                id="bad.flag_sensitive",
                label="Bad Flag Sensitive",
                description="Bad action",
                argv=("/bin/echo", "--path=../Sensitive/file.md"),
                cwd=test_config.paths.vault,
                timeout_seconds=1,
            )
        ],
    )
    with pytest.raises(ToolPolicyDenied):
        await runner.execute("bad.flag_sensitive")
    await runner.db.close()


@pytest.mark.asyncio
async def test_action_runner_denies_sensitive_cwd(test_config):
    runner = await _runner_for_specs(
        test_config,
        [
            ActionSpec(
                id="bad.cwd_sensitive",
                label="Bad Cwd Sensitive",
                description="Bad action",
                argv=("/bin/echo", "hello"),
                cwd=test_config.paths.sensitive,
                timeout_seconds=1,
            )
        ],
    )
    with pytest.raises(ToolPolicyDenied):
        await runner.execute("bad.cwd_sensitive")
    await runner.db.close()


@pytest.mark.asyncio
async def test_action_runner_denies_cwd_outside_allowed_roots(test_config, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    runner = await _runner_for_specs(
        test_config,
        [
            ActionSpec(
                id="bad.cwd_outside",
                label="Bad Cwd Outside",
                description="Bad action",
                argv=("/bin/echo", "hello"),
                cwd=outside,
                timeout_seconds=1,
            )
        ],
    )
    with pytest.raises(ToolPolicyDenied):
        await runner.execute("bad.cwd_outside")
    await runner.db.close()


@pytest.mark.asyncio
async def test_action_runner_timeout_returns_structured_result(test_config, tmp_path):
    script = _write_script(tmp_path / "slow.py", "import time\ntime.sleep(2)\n")
    runner = await _runner_for_specs(
        test_config,
        [
            ActionSpec(
                id="test.timeout",
                label="Timeout",
                description="Timeout action",
                argv=(sys.executable, str(script)),
                cwd=test_config.paths.llm_workspace,
                timeout_seconds=0.1,
            )
        ],
    )
    result = await runner.execute("test.timeout")
    await runner.db.close()
    assert result["status"] == "timeout"
    assert result["error_code"] == "TOOL_TIMEOUT"
    assert "Timed out after" in Path(result["stderr_path"]).read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_action_runner_nonzero_exit_is_failed_result(test_config, tmp_path):
    script = _write_script(
        tmp_path / "fail.py",
        "import sys\nprint('bad stderr', file=sys.stderr)\nsys.exit(7)\n",
    )
    runner = await _runner_for_specs(
        test_config,
        [
            ActionSpec(
                id="test.fail",
                label="Fail",
                description="Fail action",
                argv=(sys.executable, str(script)),
                cwd=test_config.paths.llm_workspace,
                timeout_seconds=2,
            )
        ],
    )
    result = await runner.execute("test.fail")
    await runner.db.close()
    assert result["status"] == "failed"
    assert result["exit_code"] == 7
    assert result["stderr_preview"].strip() == "bad stderr"


@pytest.mark.asyncio
async def test_action_runner_spawn_failure_terminalizes_action_run(test_config, tmp_path):
    script = tmp_path / "not_executable.sh"
    script.write_text("#!/usr/bin/env bash\necho nope\n", encoding="utf-8")
    os.chmod(script, 0o644)
    runner = await _runner_for_specs(
        test_config,
        [
            ActionSpec(
                id="test.spawn_failure",
                label="Spawn Failure",
                description="Spawn failure action",
                argv=(str(script),),
                cwd=test_config.paths.llm_workspace,
                timeout_seconds=2,
            )
        ],
    )
    result = await runner.execute("test.spawn_failure")
    rows = await runner.db.fetchall(
        "SELECT status, error_code, error_message FROM action_runs WHERE id = ?",
        (result["id"],),
    )
    await runner.db.close()
    assert result["status"] == "failed"
    assert result["error_code"] == "TOOL_EXECUTION_ERROR"
    assert rows[0]["status"] == "failed"
    assert rows[0]["error_code"] == "TOOL_EXECUTION_ERROR"
    assert rows[0]["error_message"]


@pytest.mark.asyncio
async def test_action_runner_stores_full_output_with_preview(test_config, tmp_path):
    script = _write_script(tmp_path / "big.py", "print('x' * 5000)\n")
    runner = await _runner_for_specs(
        test_config,
        [
            ActionSpec(
                id="test.big",
                label="Big",
                description="Big action",
                argv=(sys.executable, str(script)),
                cwd=test_config.paths.llm_workspace,
                timeout_seconds=2,
            )
        ],
    )
    result = await runner.execute("test.big")
    await runner.db.close()
    assert result["status"] == "success"
    assert result["stdout_preview_truncated"] is True
    assert len(result["stdout_preview"]) == 4000
    assert len(Path(result["stdout_path"]).read_text(encoding="utf-8").strip()) == 5000


@pytest.mark.asyncio
async def test_action_runner_uses_minimal_environment(test_config, tmp_path, monkeypatch):
    monkeypatch.setenv("DELAMAIN_SECRET_TEST", "leaked")
    script = _write_script(
        tmp_path / "env.py",
        "import os\nprint(os.environ.get('DELAMAIN_SECRET_TEST', 'missing'))\n",
    )
    runner = await _runner_for_specs(
        test_config,
        [
            ActionSpec(
                id="test.env",
                label="Env",
                description="Env action",
                argv=(sys.executable, str(script)),
                cwd=test_config.paths.llm_workspace,
                timeout_seconds=2,
            )
        ],
    )
    result = await runner.execute("test.env")
    await runner.db.close()
    assert result["status"] == "success"
    assert result["stdout_preview"].strip() == "missing"


@pytest.mark.asyncio
async def test_action_runner_emits_timeout_terminal_audit(test_config, tmp_path):
    script = _write_script(tmp_path / "slow.py", "import time\ntime.sleep(2)\n")
    db = Database(test_config.database.path)
    await db.connect()
    await db.migrate()
    await db.execute("INSERT INTO conversations(id, title) VALUES ('conv_audit', 'Audit')")
    runner = ActionRunner(
        config=test_config,
        db=db,
        bus=EventBus(db),
        registry=ActionRegistry(
            [
                ActionSpec(
                    id="test.audit_timeout",
                    label="Audit Timeout",
                    description="Audit timeout action",
                    argv=(sys.executable, str(script)),
                    cwd=test_config.paths.llm_workspace,
                    timeout_seconds=0.1,
                )
            ]
        ),
    )
    await runner.execute("test.audit_timeout", conversation_id="conv_audit")
    rows = await db.fetchall(
        "SELECT payload FROM events WHERE conversation_id = 'conv_audit' AND type = 'audit' ORDER BY id"
    )
    await db.close()
    actions = [json.loads(row["payload"])["action"] for row in rows]
    assert actions == ["quick_action.started", "quick_action.timeout"]


@pytest.mark.asyncio
async def test_action_runner_emits_failed_terminal_audit(test_config, tmp_path):
    script = _write_script(tmp_path / "fail.py", "import sys\nsys.exit(2)\n")
    db = Database(test_config.database.path)
    await db.connect()
    await db.migrate()
    await db.execute("INSERT INTO conversations(id, title) VALUES ('conv_failed', 'Failed')")
    runner = ActionRunner(
        config=test_config,
        db=db,
        bus=EventBus(db),
        registry=ActionRegistry(
            [
                ActionSpec(
                    id="test.audit_failed",
                    label="Audit Failed",
                    description="Audit failed action",
                    argv=(sys.executable, str(script)),
                    cwd=test_config.paths.llm_workspace,
                    timeout_seconds=2,
                )
            ]
        ),
    )
    await runner.execute("test.audit_failed", conversation_id="conv_failed")
    rows = await db.fetchall(
        "SELECT payload FROM events WHERE conversation_id = 'conv_failed' AND type = 'audit' ORDER BY id"
    )
    await db.close()
    actions = [json.loads(row["payload"])["action"] for row in rows]
    assert actions == ["quick_action.started", "quick_action.failed"]


@pytest.mark.asyncio
async def test_action_runner_rejects_output_root_under_synced_roots(test_config):
    bad_config = test_config.__class__(
        server=test_config.server,
        database=test_config.database.__class__(
            path=test_config.paths.llm_workspace / "conversations.sqlite"
            ),
            paths=test_config.paths,
            models=test_config.models,
            copilot_budget=test_config.copilot_budget,
            tools=test_config.tools,
            runtime=test_config.runtime,
            auth=test_config.auth,
        maintenance=test_config.maintenance,
        uploads=test_config.uploads,
    )
    db = Database(test_config.database.path)
    await db.connect()
    await db.migrate()
    with pytest.raises(ToolPolicyDenied):
        ActionRunner(
            config=bad_config,
            db=db,
            bus=EventBus(db),
            registry=ActionRegistry([]),
        )
    await db.close()


async def _runner_for_specs(test_config, specs: list[ActionSpec]) -> ActionRunner:
    db = Database(test_config.database.path)
    await db.connect()
    await db.migrate()
    return ActionRunner(
        config=test_config,
        db=db,
        bus=EventBus(db),
        registry=ActionRegistry(specs),
    )


def _write_script(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    os.chmod(path, 0o755)
    return path
