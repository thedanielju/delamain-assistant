from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import stat
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

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
            WorkerType(
                id="unsupported_worker",
                label="Unsupported Worker",
                description="A worker on an unsupported host.",
                command_template=("/bin/bash",),
                host="mac",
                cwd=tmp_path,
            ),
        ]
    )


def _has_tmux() -> bool:
    return Path("/usr/bin/tmux").exists()


tmux_required = pytest.mark.skipif(not _has_tmux(), reason="tmux not available")

_TEST_LOOP: asyncio.AbstractEventLoop | None = None


def _event_loop() -> asyncio.AbstractEventLoop:
    global _TEST_LOOP
    if _TEST_LOOP is None or _TEST_LOOP.is_closed():
        _TEST_LOOP = asyncio.new_event_loop()
        asyncio.set_event_loop(_TEST_LOOP)
    return _TEST_LOOP


class _FakePtySubscription:
    def __init__(self, chunks: list[str] | None = None):
        self._queue: asyncio.Queue[str | None] = asyncio.Queue()
        for chunk in chunks or []:
            self._queue.put_nowait(chunk)
        self.closed = False

    async def receive(self):
        return await self._queue.get()

    async def close(self):
        self.closed = True


def test_list_worker_types(test_config):
    app = create_app(test_config)
    with TestClient(app) as client:
        resp = client.get("/api/workers/types")
        assert resp.status_code == 200
        types = resp.json()["types"]
        types_by_id = {worker_type["id"]: worker_type for worker_type in types}
        assert "shell" in types_by_id
        assert "opencode" in types_by_id
        assert "claude_code" in types_by_id
        assert "codex_cli" in types_by_id
        assert "gemini_cli" in types_by_id
        assert "winpc_shell" in types_by_id
        assert "winpc_opencode" in types_by_id
        assert "winpc_claude_code" in types_by_id
        assert "winpc_codex_cli" in types_by_id
        assert "winpc_gemini_cli" in types_by_id

        assert types_by_id["winpc_opencode"]["host"] == "winpc"
        assert types_by_id["winpc_opencode"]["command_template"] == [
            "/home/daniel/.local/bin/opencode"
        ]
        assert types_by_id["winpc_claude_code"]["host"] == "winpc"
        assert types_by_id["winpc_claude_code"]["command_template"] == [
            "claude",
            "--dangerously-skip-permissions",
        ]
        assert types_by_id["winpc_codex_cli"]["host"] == "winpc"
        assert types_by_id["winpc_codex_cli"]["command_template"] == [
            "/home/daniel/.local/bin/codex-wsl",
            "--yolo",
        ]
        assert types_by_id["winpc_gemini_cli"]["host"] == "winpc"
        assert types_by_id["winpc_gemini_cli"]["command_template"] == [
            "gemini",
            "--yolo",
        ]


@tmux_required
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

        loop = _event_loop()

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


@tmux_required
def test_duplicate_worker_name_rejected(test_config, shell_worker_registry, tmp_path):
    """Cannot start two workers with the same name."""
    socket_path = tmp_path / "test-workers.sock"
    app = create_app(test_config)
    with TestClient(app) as client:
        from delamain_backend.workers.manager import WorkerManager

        loop = _event_loop()
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

        loop = _event_loop()
        mgr = WorkerManager(
            config=test_config,
            db=app.state.db,
            bus=app.state.bus,
            registry=shell_worker_registry,
            tmux_socket=str(socket_path),
        )

        with pytest.raises(ValueError, match="Unknown worker type"):
            loop.run_until_complete(mgr.start("nonexistent_type"))


def test_unsupported_host_rejected(test_config, shell_worker_registry, tmp_path):
    socket_path = tmp_path / "test-workers.sock"
    app = create_app(test_config)
    with TestClient(app) as client:
        from delamain_backend.workers.manager import WorkerManager

        loop = _event_loop()
        mgr = WorkerManager(
            config=test_config,
            db=app.state.db,
            bus=app.state.bus,
            registry=shell_worker_registry,
            tmux_socket=str(socket_path),
        )

        with pytest.raises(ValueError, match="Unsupported worker host"):
            loop.run_until_complete(mgr.start("unsupported_worker"))


def test_winpc_worker_uses_ssh_wsl_tmux_adapter(test_config, shell_worker_registry, tmp_path, monkeypatch):
    socket_path = tmp_path / "test-workers.sock"
    app = create_app(test_config)

    class FakeProc:
        returncode = 0

        async def communicate(self):
            return b"", b""

    async def fake_start(self, wtype, session_name, cwd):
        assert wtype.host == "winpc"
        assert session_name.startswith("dw-worker_")
        return FakeProc()

    async def fake_alive(self, session_name, *, host, tmux_socket=None):
        assert host == "winpc"
        return True

    from delamain_backend.workers.manager import WorkerManager, _winpc_tmux_command

    monkeypatch.setattr(WorkerManager, "_start_session_process", fake_start)
    monkeypatch.setattr(WorkerManager, "_session_alive", fake_alive)

    with TestClient(app):
        loop = _event_loop()
        mgr = WorkerManager(
            config=test_config,
            db=app.state.db,
            bus=app.state.bus,
            registry=shell_worker_registry,
            tmux_socket=str(socket_path),
        )
        result = loop.run_until_complete(mgr.start("remote_worker", name="winpc-test"))
        assert result["status"] == "running"
        assert result["host"] == "winpc"
        assert result["worker_type"] == "remote_worker"
        assert _winpc_tmux_command("has-session", "-t", "dw-worker_abc") == (
            "wsl.exe -e tmux has-session -t dw-worker_abc"
        )


def test_local_worker_tmux_new_session_sets_initial_cwd(
    test_config,
    shell_worker_registry,
    tmp_path,
    monkeypatch,
):
    socket_path = tmp_path / "test-workers.sock"
    app = create_app(test_config)
    calls = []

    class FakeProc:
        returncode = 0

        async def communicate(self):
            return b"", b""

    async def fake_create_subprocess_exec(*args, **kwargs):
        calls.append((args, kwargs))
        return FakeProc()

    from delamain_backend.workers.manager import WorkerManager

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    with TestClient(app):
        loop = _event_loop()
        mgr = WorkerManager(
            config=test_config,
            db=app.state.db,
            bus=app.state.bus,
            registry=shell_worker_registry,
            tmux_socket=str(socket_path),
        )
        wtype = shell_worker_registry.get("test_shell")
        assert wtype is not None
        loop.run_until_complete(
            mgr._start_session_process(wtype, "dw-worker_test", str(tmp_path))
        )

    args, kwargs = calls[0]
    assert args[:6] == (
        "/usr/bin/tmux",
        "-S",
        str(socket_path),
        "new-session",
        "-d",
        "-s",
    )
    assert args[6:10] == ("dw-worker_test", "-c", str(tmp_path), "-x")
    assert kwargs["cwd"] == str(tmp_path)


@tmux_required
def test_stop_already_stopped_rejected(test_config, shell_worker_registry, tmp_path):
    socket_path = tmp_path / "test-workers.sock"
    app = create_app(test_config)
    with TestClient(app) as client:
        from delamain_backend.workers.manager import WorkerManager

        loop = _event_loop()
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


@tmux_required
def test_kill_already_stopped_rejected(test_config, shell_worker_registry, tmp_path):
    socket_path = tmp_path / "test-workers.sock"
    app = create_app(test_config)
    with TestClient(app) as client:
        from delamain_backend.workers.manager import WorkerManager

        loop = _event_loop()
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

        loop = _event_loop()
        mgr = WorkerManager(
            config=test_config,
            db=app.state.db,
            bus=app.state.bus,
            registry=shell_worker_registry,
            tmux_socket=str(socket_path),
        )

        with pytest.raises(ValueError, match="not found"):
            loop.run_until_complete(mgr.get_worker("worker_nonexistent"))


@tmux_required
def test_refresh_detects_dead_session(test_config, shell_worker_registry, tmp_path):
    """If a tmux session dies externally, refresh_status should mark it stopped."""
    socket_path = tmp_path / "test-workers.sock"
    app = create_app(test_config)
    with TestClient(app) as client:
        from delamain_backend.workers.manager import WorkerManager
        import subprocess

        loop = _event_loop()
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

        loop = _event_loop()
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


@tmux_required
def test_conversation_scoped_worker_list(test_config, shell_worker_registry, tmp_path):
    socket_path = tmp_path / "test-workers.sock"
    app = create_app(test_config)
    with TestClient(app) as client:
        from delamain_backend.workers.manager import WorkerManager

        loop = _event_loop()
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


@tmux_required
def test_worker_rename_persists_and_emits_audit(test_config, shell_worker_registry, tmp_path):
    socket_path = tmp_path / "test-workers.sock"
    app = create_app(test_config)
    with TestClient(app) as client:
        from delamain_backend.workers.manager import WorkerManager

        loop = _event_loop()
        mgr = WorkerManager(
            config=test_config,
            db=app.state.db,
            bus=app.state.bus,
            registry=shell_worker_registry,
            tmux_socket=str(socket_path),
        )

        conv_id = client.post("/api/conversations", json={}).json()["id"]
        result = loop.run_until_complete(
            mgr.start("test_shell", name="rename-before", conversation_id=conv_id)
        )
        worker_id = result["id"]

        renamed = loop.run_until_complete(mgr.rename(worker_id, "rename-after"))
        assert renamed["name"] == "rename-after"

        row = loop.run_until_complete(mgr.get_worker(worker_id))
        assert row["name"] == "rename-after"

        con = sqlite3.connect(test_config.database.path)
        event = con.execute(
            "SELECT payload FROM events WHERE conversation_id = ? AND type = 'audit' ORDER BY id DESC LIMIT 1",
            (conv_id,),
        ).fetchone()
        con.close()

        payload = json.loads(event[0])
        assert payload["action"] == "worker.renamed"
        assert payload["old_name"] == "rename-before"
        assert payload["new_name"] == "rename-after"

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


def test_worker_pty_ws_missing_or_stopped_rejected(test_config):
    class FakePtyManager:
        def __init__(self, message: str):
            self.message = message

        async def prepare_pty(self, worker_id):
            raise ValueError(self.message)

    app = create_app(test_config)
    with TestClient(app) as client:
        app.state.worker_manager = FakePtyManager("Worker not found: worker_missing")
        with client.websocket_connect("/api/workers/worker_missing/pty") as ws:
            assert ws.receive_json() == {
                "type": "error",
                "message": "Worker not found: worker_missing",
            }
            with pytest.raises(WebSocketDisconnect):
                ws.receive_json()

        app.state.worker_manager = FakePtyManager("Worker is not running (status=stopped)")
        with client.websocket_connect("/api/workers/worker_stopped/pty") as ws:
            assert ws.receive_json() == {
                "type": "error",
                "message": "Worker is not running (status=stopped)",
            }
            with pytest.raises(WebSocketDisconnect):
                ws.receive_json()


def test_worker_pty_ws_initial_snapshot(test_config):
    class FakePtyManager:
        def __init__(self):
            self.capture_calls: list[tuple[str, int]] = []

        async def prepare_pty(self, worker_id):
            return {"id": worker_id, "status": "running"}

        async def capture_pty_output(self, worker_id, lines=200):
            self.capture_calls.append((worker_id, lines))
            return "older tmux line\ninitial tmux snapshot\n\n\n"

        async def subscribe_pty_output(self, worker_id):
            return _FakePtySubscription()

        async def send_terminal_input(self, worker_id, data):
            raise AssertionError("input should not be sent")

    mgr = FakePtyManager()
    app = create_app(test_config)
    with TestClient(app) as client:
        app.state.worker_manager = mgr
        with client.websocket_connect("/api/workers/worker_live/pty?lines=1") as ws:
            assert ws.receive_json() == {
                "type": "snapshot",
                "data": "initial tmux snapshot\n",
            }
        assert mgr.capture_calls[0] == ("worker_live", 2000)


def test_worker_pty_ws_input_calls_manager(test_config):
    class FakePtyManager:
        def __init__(self):
            self.inputs: list[tuple[str, str]] = []

        async def prepare_pty(self, worker_id):
            return {"id": worker_id, "status": "running"}

        async def capture_pty_output(self, worker_id, lines=200):
            return "ready\n"

        async def subscribe_pty_output(self, worker_id):
            return _FakePtySubscription()

        async def send_terminal_input(self, worker_id, data):
            self.inputs.append((worker_id, data))

    mgr = FakePtyManager()
    app = create_app(test_config)
    with TestClient(app) as client:
        app.state.worker_manager = mgr
        with client.websocket_connect("/api/workers/worker_live/pty") as ws:
            assert ws.receive_json()["type"] == "snapshot"
            ws.send_json({"type": "input", "data": "echo hello\r"})
        assert mgr.inputs == [("worker_live", "echo hello\r")]


def test_worker_pty_ws_snapshot_fanout(test_config):
    class FakePtyManager:
        async def prepare_pty(self, worker_id):
            return {"id": worker_id, "status": "running"}

        async def capture_pty_output(self, worker_id, lines=200):
            return f"snapshot for {worker_id}\n"

        async def subscribe_pty_output(self, worker_id):
            return _FakePtySubscription()

        async def send_terminal_input(self, worker_id, data):
            raise AssertionError("input should not be sent")

    app = create_app(test_config)
    with TestClient(app) as client:
        app.state.worker_manager = FakePtyManager()
        with client.websocket_connect("/api/workers/worker_live/pty") as ws1:
            with client.websocket_connect("/api/workers/worker_live/pty") as ws2:
                assert ws1.receive_json() == {
                    "type": "snapshot",
                    "data": "snapshot for worker_live\n",
                }
                assert ws2.receive_json() == {
                    "type": "snapshot",
                    "data": "snapshot for worker_live\n",
                }


def test_worker_pty_ws_streams_pipe_data(test_config):
    class FakePtyManager:
        async def prepare_pty(self, worker_id):
            return {"id": worker_id, "status": "running"}

        async def capture_pty_output(self, worker_id, lines=200):
            return "snapshot\n"

        async def subscribe_pty_output(self, worker_id):
            return _FakePtySubscription(["pipe chunk\n"])

        async def send_terminal_input(self, worker_id, data):
            raise AssertionError("input should not be sent")

    app = create_app(test_config)
    with TestClient(app) as client:
        app.state.worker_manager = FakePtyManager()
        with client.websocket_connect("/api/workers/worker_live/pty") as ws:
            assert ws.receive_json() == {"type": "snapshot", "data": "snapshot\n"}
            assert ws.receive_json() == {"type": "data", "data": "pipe chunk\n"}


def test_worker_terminal_input_uses_tmux_send_keys_for_local_and_winpc(
    test_config,
    shell_worker_registry,
    tmp_path,
    monkeypatch,
):
    socket_path = tmp_path / "test-workers.sock"
    app = create_app(test_config)
    calls = []

    async def fake_alive(self, session_name, *, host, tmux_socket=None):
        return True

    async def fake_send_keys(self, session_name, host, *keys, tmux_socket=None):
        calls.append((session_name, host, keys))

    from delamain_backend.workers.manager import WorkerManager

    monkeypatch.setattr(WorkerManager, "_session_alive", fake_alive)
    monkeypatch.setattr(WorkerManager, "_send_keys", fake_send_keys)

    with TestClient(app):
        loop = _event_loop()
        mgr = WorkerManager(
            config=test_config,
            db=app.state.db,
            bus=app.state.bus,
            registry=shell_worker_registry,
            tmux_socket=str(socket_path),
        )
        loop.run_until_complete(
            app.state.db.execute(
                """
                INSERT INTO workers(
                    id, name, worker_type, host, tmux_session, tmux_socket, command, status
                ) VALUES
                    ('worker_local_pty', 'local-pty', 'test_shell', 'serrano', 'dw-local', ?, '', 'running'),
                    ('worker_winpc_pty', 'winpc-pty', 'remote_worker', 'winpc', 'dw-winpc', ?, '', 'running')
                """,
                (str(socket_path), str(socket_path)),
            )
        )

        loop.run_until_complete(mgr.send_terminal_input("worker_local_pty", "abc\r\x1b[A"))
        loop.run_until_complete(mgr.send_terminal_input("worker_winpc_pty", "xyz\x7f"))

    assert calls == [
        ("dw-local", "serrano", ("-l", "abc")),
        ("dw-local", "serrano", ("Enter",)),
        ("dw-local", "serrano", ("Up",)),
        ("dw-winpc", "winpc", ("-l", "xyz")),
        ("dw-winpc", "winpc", ("BSpace",)),
    ]


@tmux_required
def test_worker_rename_endpoint(test_config, shell_worker_registry, tmp_path):
    socket_path = tmp_path / "test-workers.sock"
    app = create_app(test_config)
    with TestClient(app) as client:
        from delamain_backend.workers.manager import WorkerManager

        loop = _event_loop()
        app.state.worker_manager = WorkerManager(
            config=test_config,
            db=app.state.db,
            bus=app.state.bus,
            registry=shell_worker_registry,
            tmux_socket=str(socket_path),
        )

        created = loop.run_until_complete(
            app.state.worker_manager.start("test_shell", name="endpoint-before")
        )
        renamed = client.patch(
            f"/api/workers/{created['id']}",
            json={"name": "endpoint-after"},
        )
        assert renamed.status_code == 200
        assert renamed.json()["name"] == "endpoint-after"

        loop.run_until_complete(app.state.worker_manager.kill(created["id"]))
        if socket_path.exists():
            socket_path.unlink()


@tmux_required
def test_worker_audit_events(test_config, shell_worker_registry, tmp_path):
    """Worker start/kill should emit audit events."""
    socket_path = tmp_path / "test-workers.sock"
    app = create_app(test_config)
    with TestClient(app) as client:
        from delamain_backend.workers.manager import WorkerManager

        loop = _event_loop()
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
