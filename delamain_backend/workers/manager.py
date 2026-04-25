from __future__ import annotations

import asyncio
import json
import os
import uuid
from pathlib import Path
from typing import Any

from delamain_backend.config import AppConfig
from delamain_backend.db import Database
from delamain_backend.events import EventBus
from delamain_backend.workers.registry import WorkerType, WorkerTypeRegistry

WORKER_TMUX_SOCKET = "/home/danielju/.local/share/delamain/workers.sock"
SESSION_PREFIX = "dw-"
CAPTURE_LINES = 200
SUPPORTED_WORKER_HOSTS = {"serrano", "winpc"}
PTY_CAPTURE_LINES = 200


_TERMINAL_INPUT_KEYS = {
    "\r": "Enter",
    "\n": "Enter",
    "\t": "Tab",
    "\x7f": "BSpace",
    "\b": "BSpace",
    "\x03": "C-c",
    "\x04": "C-d",
    "\x1b[A": "Up",
    "\x1b[B": "Down",
    "\x1b[C": "Right",
    "\x1b[D": "Left",
    "\x1b[3~": "Delete",
    "\x1b[H": "Home",
    "\x1b[F": "End",
    "\x1b[5~": "PageUp",
    "\x1b[6~": "PageDown",
}


class WorkerManager:
    def __init__(
        self,
        *,
        config: AppConfig,
        db: Database,
        bus: EventBus | None,
        registry: WorkerTypeRegistry,
        tmux_socket: str | None = None,
    ):
        self.config = config
        self.db = db
        self.bus = bus
        self.registry = registry
        self.tmux_socket = Path(tmux_socket or WORKER_TMUX_SOCKET)
        self._input_locks: dict[str, asyncio.Lock] = {}

    async def start(
        self,
        worker_type_id: str,
        *,
        name: str | None = None,
        conversation_id: str | None = None,
    ) -> dict[str, Any]:
        wtype = self.registry.get(worker_type_id)
        if wtype is None:
            raise ValueError(f"Unknown worker type: {worker_type_id}")

        if wtype.host not in SUPPORTED_WORKER_HOSTS:
            raise ValueError(f"Unsupported worker host: {wtype.host}")

        worker_id = f"worker_{uuid.uuid4().hex[:12]}"
        session_name = f"{SESSION_PREFIX}{worker_id}"
        if name is None:
            name = f"{wtype.id}-{worker_id[-6:]}"

        if conversation_id is not None:
            conv = await self.db.fetchone(
                "SELECT id FROM conversations WHERE id = ?", (conversation_id,)
            )
            if conv is None:
                raise ValueError(f"Conversation not found: {conversation_id}")

        existing = await self.db.fetchone(
            "SELECT id FROM workers WHERE name = ? AND status IN ('running', 'starting')",
            (name,),
        )
        if existing is not None:
            raise ValueError(f"A worker named '{name}' is already running")

        cwd = str(wtype.cwd) if wtype.cwd else str(Path.home())
        command = " ".join(wtype.command_template)

        await self.db.execute(
            """
            INSERT INTO workers(
                id, name, worker_type, host, tmux_session, tmux_socket,
                conversation_id, command, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'starting')
            """,
            (
                worker_id,
                name,
                wtype.id,
                wtype.host,
                session_name,
                str(self.tmux_socket),
                conversation_id,
                command,
            ),
        )

        try:
            proc = await self._start_session_process(wtype, session_name, cwd)
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=15)
            if proc.returncode != 0:
                error = stderr.decode("utf-8", errors="replace").strip()
                await self._mark_failed(worker_id, error)
                return await self._worker_out(worker_id)
        except asyncio.TimeoutError:
            # tmux server cold-start can be slow; check if session came up
            if not await self._session_alive(session_name, host=wtype.host):
                await self._mark_failed(worker_id, "tmux session creation timed out")
                return await self._worker_out(worker_id)
        except Exception as exc:
            await self._mark_failed(worker_id, str(exc))
            return await self._worker_out(worker_id)

        alive = await self._session_alive(session_name, host=wtype.host)
        status = "running" if alive else "failed"
        if status == "running":
            await self.db.execute(
                """
                UPDATE workers
                SET status = 'running',
                    updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                WHERE id = ?
                """,
                (worker_id,),
            )
        else:
            await self._mark_failed(worker_id, "Session exited immediately after creation")

        await self._audit(
            conversation_id,
            f"worker.{'started' if status == 'running' else 'failed'}",
            f"Worker {name} ({wtype.id}) {status}",
            {"worker_id": worker_id, "name": name, "worker_type": wtype.id, "status": status},
        )
        return await self._worker_out(worker_id)

    async def stop(self, worker_id: str) -> dict[str, Any]:
        row = await self._get_worker(worker_id)
        if row["status"] not in ("running", "starting"):
            raise ValueError(f"Worker is not running (status={row['status']})")
        session_name = row["tmux_session"]
        try:
            await self._send_keys(
                session_name,
                row["host"],
                "C-c",
                "",
                tmux_socket=row.get("tmux_socket"),
            )
            await asyncio.sleep(0.5)
            await self._send_keys(
                session_name,
                row["host"],
                "exit",
                "Enter",
                tmux_socket=row.get("tmux_socket"),
            )
            await asyncio.sleep(1)
        except Exception:
            pass
        alive = await self._session_alive(
            session_name,
            host=row["host"],
            tmux_socket=row.get("tmux_socket"),
        )
        if alive:
            await self.db.execute(
                """
                UPDATE workers
                SET status = 'stopping',
                    updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                WHERE id = ?
                """,
                (worker_id,),
            )
        else:
            await self.db.execute(
                """
                UPDATE workers
                SET status = 'stopped',
                    stopped_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
                    updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                WHERE id = ?
                """,
                (worker_id,),
            )
        await self._audit(
            row.get("conversation_id"),
            "worker.stop_requested",
            f"Worker {row['name']} stop requested",
            {"worker_id": worker_id, "name": row["name"]},
        )
        return await self._worker_out(worker_id)

    async def kill(self, worker_id: str) -> dict[str, Any]:
        row = await self._get_worker(worker_id)
        if row["status"] in ("stopped", "failed"):
            raise ValueError(f"Worker is already {row['status']}")
        session_name = row["tmux_session"]
        try:
            await self._kill_session(session_name, row["host"], tmux_socket=row.get("tmux_socket"))
        except Exception:
            pass
        await self.db.execute(
            """
            UPDATE workers
            SET status = 'stopped',
                stopped_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
                updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            WHERE id = ?
            """,
            (worker_id,),
        )
        await self._audit(
            row.get("conversation_id"),
            "worker.killed",
            f"Worker {row['name']} killed",
            {"worker_id": worker_id, "name": row["name"]},
        )
        return await self._worker_out(worker_id)

    async def capture_output(self, worker_id: str, lines: int = CAPTURE_LINES) -> dict[str, Any]:
        row = await self._get_worker(worker_id)
        session_name = row["tmux_session"]
        alive = await self._session_alive(
            session_name,
            host=row["host"],
            tmux_socket=row.get("tmux_socket"),
        )
        output = ""
        if alive:
            try:
                proc = await self._capture_process(
                    session_name,
                    row["host"],
                    lines,
                    tmux_socket=row.get("tmux_socket"),
                )
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
                if proc.returncode == 0:
                    output = stdout.decode("utf-8", errors="replace")
            except Exception:
                pass
        return {
            "worker_id": worker_id,
            "name": row["name"],
            "alive": alive,
            "lines_requested": lines,
            "output": output,
        }

    async def prepare_pty(self, worker_id: str) -> dict[str, Any]:
        row = await self._get_worker(worker_id)
        if row["status"] != "running":
            raise ValueError(f"Worker is not running (status={row['status']})")
        alive = await self._session_alive(
            row["tmux_session"],
            host=row["host"],
            tmux_socket=row.get("tmux_socket"),
        )
        if not alive:
            await self.db.execute(
                """
                UPDATE workers
                SET status = 'stopped',
                    stopped_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
                    updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                WHERE id = ?
                """,
                (worker_id,),
            )
            raise ValueError("Worker tmux session is gone")
        return row

    async def capture_pty_output(self, worker_id: str, lines: int = PTY_CAPTURE_LINES) -> str:
        row = await self.prepare_pty(worker_id)
        proc = await self._capture_process(
            row["tmux_session"],
            row["host"],
            lines,
            tmux_socket=row.get("tmux_socket"),
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=5)
        if proc.returncode != 0:
            error = stderr.decode("utf-8", errors="replace").strip()
            raise ValueError(error or "Failed to capture worker tmux pane")
        return stdout.decode("utf-8", errors="replace")

    async def send_terminal_input(self, worker_id: str, data: str) -> None:
        if not data:
            return
        row = await self.prepare_pty(worker_id)
        lock = self._input_locks.setdefault(worker_id, asyncio.Lock())
        async with lock:
            for literal, key in _terminal_input_chunks(data):
                if literal:
                    await self._send_keys(
                        row["tmux_session"],
                        row["host"],
                        "-l",
                        literal,
                        tmux_socket=row.get("tmux_socket"),
                    )
                elif key:
                    await self._send_keys(
                        row["tmux_session"],
                        row["host"],
                        key,
                        tmux_socket=row.get("tmux_socket"),
                    )

    async def rename(self, worker_id: str, name: str) -> dict[str, Any]:
        row = await self._get_worker(worker_id)
        cleaned = name.strip()
        if not cleaned:
            raise ValueError("Worker name cannot be empty")
        existing = await self.db.fetchone(
            """
            SELECT id FROM workers
            WHERE name = ? AND id != ? AND status IN ('running', 'starting')
            """,
            (cleaned, worker_id),
        )
        if existing is not None:
            raise ValueError(f"A worker named '{cleaned}' is already running")
        await self.db.execute(
            """
            UPDATE workers
            SET name = ?,
                updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            WHERE id = ?
            """,
            (cleaned, worker_id),
        )
        await self._audit(
            row.get("conversation_id"),
            "worker.renamed",
            f"Worker {row['name']} renamed to {cleaned}",
            {
                "worker_id": worker_id,
                "old_name": row["name"],
                "new_name": cleaned,
            },
        )
        return await self._worker_out(worker_id)

    async def list_workers(
        self,
        *,
        status_filter: str | None = None,
        conversation_id: str | None = None,
    ) -> list[dict[str, Any]]:
        if status_filter:
            rows = await self.db.fetchall(
                "SELECT * FROM workers WHERE status = ? ORDER BY created_at DESC",
                (status_filter,),
            )
        elif conversation_id:
            rows = await self.db.fetchall(
                "SELECT * FROM workers WHERE conversation_id = ? ORDER BY created_at DESC",
                (conversation_id,),
            )
        else:
            rows = await self.db.fetchall(
                "SELECT * FROM workers ORDER BY created_at DESC"
            )
        return [_worker_row_out(row) for row in rows]

    async def get_worker(self, worker_id: str) -> dict[str, Any]:
        return await self._worker_out(worker_id)

    async def refresh_status(self, worker_id: str) -> dict[str, Any]:
        row = await self._get_worker(worker_id)
        if row["status"] in ("running", "starting", "stopping"):
            alive = await self._session_alive(
                row["tmux_session"],
                host=row["host"],
                tmux_socket=row.get("tmux_socket"),
            )
            if not alive and row["status"] != "stopped":
                await self.db.execute(
                    """
                    UPDATE workers
                    SET status = 'stopped',
                        stopped_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
                        updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                    WHERE id = ?
                    """,
                    (worker_id,),
                )
        return await self._worker_out(worker_id)

    async def reconcile_on_startup(self) -> dict[str, int]:
        rows = await self.db.fetchall(
            "SELECT * FROM workers WHERE status IN ('running', 'starting', 'stopping')"
        )
        alive = 0
        stopped = 0
        for row in rows:
            session_alive = await self._session_alive(
                row["tmux_session"],
                host=row["host"],
                tmux_socket=row.get("tmux_socket"),
            )
            if session_alive:
                alive += 1
                if row["status"] == "starting":
                    await self.db.execute(
                        """
                        UPDATE workers
                        SET status = 'running',
                            updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                        WHERE id = ?
                        """,
                        (row["id"],),
                    )
                continue
            stopped += 1
            await self.db.execute(
                """
                UPDATE workers
                SET status = 'stopped',
                    stopped_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
                    updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                WHERE id = ?
                """,
                (row["id"],),
            )
        return {"checked": len(rows), "alive": alive, "stopped": stopped}

    async def _start_session_process(
        self,
        wtype: WorkerType,
        session_name: str,
        cwd: str,
    ) -> asyncio.subprocess.Process:
        if wtype.host == "winpc":
            return await asyncio.create_subprocess_exec(
                "/usr/bin/ssh",
                "winpc",
                _winpc_tmux_command(
                    "new-session",
                    "-d",
                    "-s",
                    session_name,
                    "-c",
                    cwd,
                    "-x",
                    "200",
                    "-y",
                    "50",
                    "--",
                    *wtype.command_template,
                ),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        self.tmux_socket.parent.mkdir(parents=True, exist_ok=True)
        return await asyncio.create_subprocess_exec(
            "/usr/bin/tmux",
            "-S", str(self.tmux_socket),
            "new-session",
            "-d",
            "-s", session_name,
            "-x", "200",
            "-y", "50",
            *wtype.command_template,
            cwd=cwd,
            env=_worker_env(wtype),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

    async def _send_keys(
        self,
        session_name: str,
        host: str,
        *keys: str,
        tmux_socket: str | None = None,
    ) -> None:
        if host == "winpc":
            proc = await asyncio.create_subprocess_exec(
                "/usr/bin/ssh",
                "winpc",
                _winpc_tmux_command("send-keys", "-t", session_name, *keys),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        else:
            socket_path = str(Path(tmux_socket) if tmux_socket else self.tmux_socket)
            proc = await asyncio.create_subprocess_exec(
                "/usr/bin/tmux",
                "-S", socket_path,
                "send-keys",
                "-t", session_name,
                *keys,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        await asyncio.wait_for(proc.communicate(), timeout=5)

    async def _kill_session(
        self,
        session_name: str,
        host: str,
        tmux_socket: str | None = None,
    ) -> None:
        if host == "winpc":
            proc = await asyncio.create_subprocess_exec(
                "/usr/bin/ssh",
                "winpc",
                _winpc_tmux_command("kill-session", "-t", session_name),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        else:
            socket_path = str(Path(tmux_socket) if tmux_socket else self.tmux_socket)
            proc = await asyncio.create_subprocess_exec(
                "/usr/bin/tmux",
                "-S", socket_path,
                "kill-session",
                "-t", session_name,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        await asyncio.wait_for(proc.communicate(), timeout=5)

    async def _capture_process(
        self,
        session_name: str,
        host: str,
        lines: int,
        tmux_socket: str | None = None,
    ) -> asyncio.subprocess.Process:
        if host == "winpc":
            return await asyncio.create_subprocess_exec(
                "/usr/bin/ssh",
                "winpc",
                _winpc_tmux_command(
                    "capture-pane",
                    "-p",
                    "-t",
                    session_name,
                    "-S",
                    str(-lines),
                ),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        socket_path = str(Path(tmux_socket) if tmux_socket else self.tmux_socket)
        return await asyncio.create_subprocess_exec(
            "/usr/bin/tmux",
            "-S", socket_path,
            "capture-pane",
            "-p",
            "-t", session_name,
            "-S", str(-lines),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

    async def _session_alive(
        self,
        session_name: str,
        *,
        host: str,
        tmux_socket: str | None = None,
    ) -> bool:
        try:
            if host == "winpc":
                proc = await asyncio.create_subprocess_exec(
                    "/usr/bin/ssh",
                    "winpc",
                    _winpc_tmux_command("has-session", "-t", session_name),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
            else:
                socket_path = str(Path(tmux_socket) if tmux_socket else self.tmux_socket)
                proc = await asyncio.create_subprocess_exec(
                    "/usr/bin/tmux",
                    "-S", socket_path,
                    "has-session",
                    "-t", session_name,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
            await asyncio.wait_for(proc.communicate(), timeout=5)
            return proc.returncode == 0
        except Exception:
            return False

    async def _get_worker(self, worker_id: str) -> dict[str, Any]:
        row = await self.db.fetchone("SELECT * FROM workers WHERE id = ?", (worker_id,))
        if row is None:
            raise ValueError(f"Worker not found: {worker_id}")
        return row

    async def _worker_out(self, worker_id: str) -> dict[str, Any]:
        row = await self._get_worker(worker_id)
        return _worker_row_out(row)

    async def _mark_failed(self, worker_id: str, error: str) -> None:
        await self.db.execute(
            """
            UPDATE workers
            SET status = 'failed',
                error_message = ?,
                stopped_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
                updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            WHERE id = ?
            """,
            (error, worker_id),
        )

    async def _audit(
        self,
        conversation_id: str | None,
        action: str,
        summary: str,
        payload: dict[str, Any],
    ) -> None:
        if self.bus is None or conversation_id is None:
            return
        await self.bus.emit(
            conversation_id=conversation_id,
            run_id=None,
            event_type="audit",
            payload={"action": action, "summary": summary, **payload},
        )


def _worker_env(wtype: WorkerType) -> dict[str, str]:
    env = {
        "HOME": str(Path.home()),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "LC_ALL": os.environ.get("LC_ALL", "C.UTF-8"),
        "PATH": (
            "/home/danielju/.npm-global/bin:"
            "/home/danielju/.local/bin:"
            "/usr/local/bin:/usr/bin:/bin"
        ),
        "TZ": os.environ.get("TZ", "America/New_York"),
        "TERM": "xterm-256color",
        "USER": os.environ.get("USER", "danielju"),
        "XDG_RUNTIME_DIR": os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"),
    }
    for key in ("GOOGLE_API_KEY", "GEMINI_API_KEY"):
        if os.environ.get(key):
            env[key] = os.environ[key]
    env.update(wtype.env_extras)
    return env


def _worker_row_out(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    if "metadata_json" in out:
        try:
            out["metadata"] = json.loads(out.pop("metadata_json"))
        except (json.JSONDecodeError, TypeError):
            out["metadata"] = {}
    return out


def _terminal_input_chunks(data: str) -> list[tuple[str | None, str | None]]:
    chunks: list[tuple[str | None, str | None]] = []
    literal: list[str] = []
    special_sequences = sorted(_TERMINAL_INPUT_KEYS, key=len, reverse=True)

    def flush_literal() -> None:
        if literal:
            chunks.append(("".join(literal), None))
            literal.clear()

    i = 0
    while i < len(data):
        matched_sequence: str | None = None
        if data[i] == "\x1b":
            for sequence in special_sequences:
                if data.startswith(sequence, i):
                    matched_sequence = sequence
                    break
        elif data[i] in _TERMINAL_INPUT_KEYS:
            matched_sequence = data[i]

        if matched_sequence is not None:
            flush_literal()
            chunks.append((None, _TERMINAL_INPUT_KEYS[matched_sequence]))
            i += len(matched_sequence)
            continue

        literal.append(data[i])
        i += 1

    flush_literal()
    return chunks


def _winpc_tmux_command(*args: str) -> str:
    return " ".join(("wsl.exe", "-e", "tmux", *(_quote_remote_arg(arg) for arg in args)))


def _quote_remote_arg(arg: str) -> str:
    if all(ch.isalnum() or ch in "-_./:" for ch in arg):
        return arg
    return "'" + arg.replace("'", "'\"'\"'") + "'"
