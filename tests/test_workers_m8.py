from __future__ import annotations

import json
import os
import sqlite3
import stat
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from delamain_backend.main import create_app
from delamain_backend.workers.registry import WorkerType, WorkerTypeRegistry


@pytest.fixture
def shell_worker_registry(tmp_path):
    """Registry with a simple shell worker type for testing."""
    script = tmp_path / "test-worker.sh"
    script.write_text("#!/bin/bash\nwhile true; do sleep 1; done\n", encoding="utf-8")
    os.chmod(script, 0o755)
    return WorkerTypeRegistry(
        [
            WorkerType(
                id="test_shell",
                label="Test Shell",
                description="A test shell worker.",
                command_template=(str(script),),
                host="serrano",
                cwd=tmp_path,
            ),
            WorkerType(
                id="bad_command",
                label="Bad Command",
                description="A worker with a nonexistent command.",
                command_template=("/nonexistent/command",),
                host="serrano",
                cwd=tmp_path,
            ),
            WorkerType(
                id="remote_worker",
                label="Remote Worker",
                description="A worker on a remote host.",
                command_template=("/bin/bash",),
                host="winpc",
                cwd=tmp_path,
            ),
        ]
    )


def _has_tmux() -> bool:
    return Path("/usr/bin/tmux").exists()


pytestmark = pytest.mark.skipif(not _has_tmux(), reason="tmux not available")


def test_list_worker_types(test_config):
    app = create_app(test_config)
    with TestClient(app) as client:
        resp = client.get("/api/workers/types")
        assert resp.status_code == 200
        types = resp.json()["types"]
        type_ids = [t["id"] for t in types]
        assert "shell" in type_ids
        assert "opencode" in type_ids
        assert "claude_code" in type_ids


def test_start_shell_worker_and_lifecycle(test_config, shell_worker_registry, tmp_path):
    """Start a shell worker, verify it runs, capture output, stop, kill."""
    socket_path = tmp_path / "test-workers.sock"
    app = create_app(test_config)
    with TestClient(app) as client:
        # Inject custom registry and socket for testing
        from delamain_backend.workers.manager import WorkerManager

        conv_id = client.post("/api/conversations", json={}).json()["id"]

        mgr = WorkerManager(
            config=test_config,
            db=app.state.db,
            bus=app.state.bus,
            registry=shell_worker_registry,
            tmux_socket=str(socket_path),
        )

        import asyncio

        loop = asyncio.get_event_loop()

        # Start a shell worker
        result = loop.run_until_complete(
            mgr.start("test_shell", name="test-worker-1", conversation_id=conv_id)
        )
        assert result["status"] == "running"
        assert result["name"] == "test-worker-1"
        assert result["worker_type"] == "test_shell"
        worker_id = result["id"]

        # List workers
        workers = loop.run_until_complete(mgr.list_workers())
        assert len(workers) >= 1
        assert any(w["id"] == worker_id for w in workers)

        # Get worker
        fetched = loop.run_until_complete(mgr.get_worker(worker_id))
        assert fetched["id"] == worker_id
        assert fetched["status"] == "running"

        # Capture output
        output = loop.run_until_complete(mgr.capture_output(worker_id))
        assert output["worker_id"] == worker_id
        assert output["alive"] is True

        # Refresh status (should stay running)
        refreshed = loop.run_until_complete(mgr.refresh_status(worker_id))
        assert refreshed["status"] == "running"

        # Kill the worker
        killed = loop.run_until_complete(mgr.kill(worker_id))
        assert killed["status"] == "stopped"

        # Verify in DB
        db_row = loop.run_until_complete(
            app.state.db.fetchone("SELECT * FROM workers WHERE id = ?", (worker_id,))
        )
        assert db_row["status"] == "stopped"
        assert db_row["stopped_at"] is not None

        # Cleanup tmux socket
        if socket_path.exists():
            socket_path.unlink()


def test_duplicate_worker_name_rejected(test_config, shell_worker_registry, tmp_path):
    """Cannot start two workers with the same name."""
    socket_path = tmp_path / "test-workers.sock"
    app = create_app(test_config)
    with TestClient(app) as client:
        from delamain_backend.workers.manager import WorkerManager
        import asyncio

        loop = asyncio.get_event_loop()
        mgr = WorkerManager(
            config=test_config,
            db=app.state.db,
            bus=app.state.bus,
            registry=shell_worker_registry,
            tmux_socket=str(socket_path),
        )

        result = loop.run_until_complete(mgr.start("test_shell", name="unique-name"))
        assert result["status"] == "running"
        worker_id = result["id"]

        with pytest.raises(ValueError, match="already running"):
            loop.run_until_complete(mgr.start("test_shell", name="unique-name"))

        loop.run_until_complete(mgr.kill(worker_id))
        if socket_path.exists():
            socket_path.unlink()


def test_unknown_worker_type_rejected(test_config, shell_worker_registry, tmp_path):
    socket_path = tmp_path / "test-workers.sock"
    app = create_app(test_config)
    with TestClient(app) as client:
        from delamain_backend.workers.manager import WorkerManager
        import asyncio

        loop = asyncio.get_event_loop()
        mgr = WorkerManager(
            config=test_config,
            db=app.state.db,
            bus=app.state.bus,
            registry=shell_worker_registry,
            tmux_socket=str(socket_path),
        )

        with pytest.raises(ValueError, match="Unknown worker type"):
            loop.run_until_complete(mgr.start("nonexistent_type"))


def test_remote_host_rejected(test_config, shell_worker_registry, tmp_path):
    """Only serrano workers are supported for now."""
    socket_path = tmp_path / "test-workers.sock"
    app = create_app(test_config)
    with TestClient(app) as client:
        from delamain_backend.workers.manager import WorkerManager
        import asyncio

        loop = asyncio.get_event_loop()
        mgr = WorkerManager(
            config=test_config,
            db=app.state.db,
            bus=app.state.bus,
            registry=shell_worker_registry,
            tmux_socket=str(socket_path),
        )

        with pytest.raises(ValueError, match="Only serrano"):
            loop.run_until_complete(mgr.start("remote_worker"))


def test_stop_already_stopped_rejected(test_config, shell_worker_registry, tmp_path):
    socket_path = tmp_path / "test-workers.sock"
    app = create_app(test_config)
    with TestClient(app) as client:
        from delamain_backend.workers.manager import WorkerManager
        import asyncio

        loop = asyncio.get_event_loop()
        mgr = WorkerManager(
            config=test_config,
            db=app.state.db,
            bus=app.state.bus,
            registry=shell_worker_registry,
            tmux_socket=str(socket_path),
        )

        result = loop.run_until_complete(mgr.start("test_shell", name="stop-test"))
        worker_id = result["id"]
        loop.run_until_complete(mgr.kill(worker_id))

        with pytest.raises(ValueError, match="not running"):
            loop.run_until_complete(mgr.stop(worker_id))

        if socket_path.exists():
            socket_path.unlink()


def test_kill_already_stopped_rejected(test_config, shell_worker_registry, tmp_path):
    socket_path = tmp_path / "test-workers.sock"
    app = create_app(test_config)
    with TestClient(app) as client:
        from delamain_backend.workers.manager import WorkerManager
        import asyncio

        loop = asyncio.get_event_loop()
        mgr = WorkerManager(
            config=test_config,
            db=app.state.db,
            bus=app.state.bus,
            registry=shell_worker_registry,
            tmux_socket=str(socket_path),
        )

        result = loop.run_until_complete(mgr.start("test_shell", name="kill-test"))
        worker_id = result["id"]
        loop.run_until_complete(mgr.kill(worker_id))

        with pytest.raises(ValueError, match="already stopped"):
            loop.run_until_complete(mgr.kill(worker_id))

        if socket_path.exists():
            socket_path.unlink()


def test_worker_not_found(test_config, shell_worker_registry, tmp_path):
    socket_path = tmp_path / "test-workers.sock"
    app = create_app(test_config)
    with TestClient(app) as client:
        from delamain_backend.workers.manager import WorkerManager
        import asyncio

        loop = asyncio.get_event_loop()
        mgr = WorkerManager(
            config=test_config,
            db=app.state.db,
            bus=app.state.bus,
            registry=shell_worker_registry,
            tmux_socket=str(socket_path),
        )

        with pytest.raises(ValueError, match="not found"):
            loop.run_until_complete(mgr.get_worker("worker_nonexistent"))


def test_refresh_detects_dead_session(test_config, shell_worker_registry, tmp_path):
    """If a tmux session dies externally, refresh_status should mark it stopped."""
    socket_path = tmp_path / "test-workers.sock"
    app = create_app(test_config)
    with TestClient(app) as client:
        from delamain_backend.workers.manager import WorkerManager
        import asyncio
        import subprocess

        loop = asyncio.get_event_loop()
        mgr = WorkerManager(
            config=test_config,
            db=app.state.db,
            bus=app.state.bus,
            registry=shell_worker_registry,
            tmux_socket=str(socket_path),
        )

        result = loop.run_until_complete(mgr.start("test_shell", name="refresh-test"))
        worker_id = result["id"]
        session_name = result["tmux_session"]

        # Kill the tmux session directly (simulating external death)
        subprocess.run(
            ["/usr/bin/tmux", "-S", str(socket_path), "kill-session", "-t", session_name],
            capture_output=True,
        )
        time.sleep(0.5)

        # Refresh should detect the dead session
        refreshed = loop.run_until_complete(mgr.refresh_status(worker_id))
        assert refreshed["status"] == "stopped"

        if socket_path.exists():
            socket_path.unlink()


def test_reconcile_on_startup_marks_dead_workers_stopped(test_config, shell_worker_registry, tmp_path):
    socket_path = tmp_path / "test-workers.sock"
    app = create_app(test_config)
    with TestClient(app) as client:
        from delamain_backend.workers.manager import WorkerManager
        import asyncio

        loop = asyncio.get_event_loop()
        mgr = WorkerManager(
            config=test_config,
            db=app.state.db,
            bus=app.state.bus,
            registry=shell_worker_registry,
            tmux_socket=str(socket_path),
        )
        worker_id = "worker_dead_reconcile"
        loop.run_until_complete(
            app.state.db.execute(
                """
                INSERT INTO workers(
                    id, name, worker_type, host, tmux_session, tmux_socket, command, status
                ) VALUES (?, 'dead-worker', 'test_shell', 'serrano', 'missing-session', ?, '', 'running')
                """,
                (worker_id, str(socket_path)),
            )
        )

        result = loop.run_until_complete(mgr.reconcile_on_startup())
        assert result["checked"] == 1
        assert result["stopped"] == 1
        row = loop.run_until_complete(mgr.get_worker(worker_id))
        assert row["status"] == "stopped"
        assert row["stopped_at"] is not None

        if socket_path.exists():
            socket_path.unlink()


def test_conversation_scoped_worker_list(test_config, shell_worker_registry, tmp_path):
    socket_path = tmp_path / "test-workers.sock"
    app = create_app(test_config)
    with TestClient(app) as client:
        from delamain_backend.workers.manager import WorkerManager
        import asyncio

        loop = asyncio.get_event_loop()
        mgr = WorkerManager(
            config=test_config,
            db=app.state.db,
            bus=app.state.bus,
            registry=shell_worker_registry,
            tmux_socket=str(socket_path),
        )

        conv_id = client.post("/api/conversations", json={}).json()["id"]
        result = loop.run_until_complete(
            mgr.start("test_shell", name="conv-test", conversation_id=conv_id)
        )
        worker_id = result["id"]

        # List by conversation
        workers = loop.run_until_complete(mgr.list_workers(conversation_id=conv_id))
        assert len(workers) == 1
        assert workers[0]["id"] == worker_id

        # List by status
        running = loop.run_until_complete(mgr.list_workers(status_filter="running"))
        assert any(w["id"] == worker_id for w in running)

        loop.run_until_complete(mgr.kill(worker_id))
        if socket_path.exists():
            socket_path.unlink()


def test_worker_api_endpoints(test_config):
    """Test the REST endpoints via TestClient."""
    app = create_app(test_config)
    with TestClient(app) as client:
        manager_id = id(app.state.worker_manager)

        # List types
        types_resp = client.get("/api/workers/types")
        assert types_resp.status_code == 200

        # List workers (empty)
        list_resp = client.get("/api/workers")
        assert list_resp.status_code == 200
        assert list_resp.json()["workers"] == []

        # Start unknown type
        bad_start = client.post(
            "/api/workers",
            json={"worker_type": "nonexistent"},
        )
        assert bad_start.status_code == 400

        # Get nonexistent worker
        not_found = client.get("/api/workers/worker_nonexistent")
        assert not_found.status_code == 404
        assert id(app.state.worker_manager) == manager_id


def test_worker_audit_events(test_config, shell_worker_registry, tmp_path):
    """Worker start/kill should emit audit events."""
    socket_path = tmp_path / "test-workers.sock"
    app = create_app(test_config)
    with TestClient(app) as client:
        from delamain_backend.workers.manager import WorkerManager
        import asyncio

        loop = asyncio.get_event_loop()
        mgr = WorkerManager(
            config=test_config,
            db=app.state.db,
            bus=app.state.bus,
            registry=shell_worker_registry,
            tmux_socket=str(socket_path),
        )

        conv_id = client.post("/api/conversations", json={}).json()["id"]
        result = loop.run_until_complete(
            mgr.start("test_shell", name="audit-test", conversation_id=conv_id)
        )
        worker_id = result["id"]
        loop.run_until_complete(mgr.kill(worker_id))

        # Check audit events
        con = sqlite3.connect(test_config.database.path)
        events = [
            json.loads(row[0])
            for row in con.execute(
                "SELECT payload FROM events WHERE conversation_id = ? AND type = 'audit'",
                (conv_id,),
            )
        ]
        con.close()

        actions = [e["action"] for e in events]
        assert "worker.started" in actions
        assert "worker.killed" in actions

        if socket_path.exists():
            socket_path.unlink()
