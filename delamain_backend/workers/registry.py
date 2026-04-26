from __future__ import annotations

import asyncio
import copy
import json
import os
import shutil
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from delamain_backend.config import AppConfig

READINESS_TTL_SECONDS = 30.0
READINESS_TIMEOUT_SECONDS = 6.0


@dataclass(frozen=True)
class WorkerType:
    id: str
    label: str
    description: str
    command_template: tuple[str, ...]
    host: str = "serrano"
    cwd: Path | None = None
    env_extras: dict[str, str] = field(default_factory=dict)

    def public_dict(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "description": self.description,
            "command_template": list(self.command_template),
            "host": self.host,
        }


class WorkerTypeRegistry:
    def __init__(self, types: list[WorkerType]):
        self._types = {wt.id: wt for wt in types}
        self._readiness_cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._readiness_locks: dict[str, asyncio.Lock] = {}

    def list(self) -> list[dict]:
        return [self._types[wt_id].public_dict() for wt_id in sorted(self._types)]

    async def list_public(
        self,
        *,
        include_readiness: bool = False,
        refresh_readiness: bool = False,
    ) -> list[dict]:
        worker_types = [self._types[wt_id] for wt_id in sorted(self._types)]
        if not include_readiness:
            return [worker_type.public_dict() for worker_type in worker_types]
        readiness = await asyncio.gather(
            *(
                self.readiness_for(worker_type.id, refresh=refresh_readiness)
                for worker_type in worker_types
            )
        )
        return [
            {**worker_type.public_dict(), "readiness": readiness_item}
            for worker_type, readiness_item in zip(worker_types, readiness, strict=True)
        ]

    def get(self, worker_type_id: str) -> WorkerType | None:
        return self._types.get(worker_type_id)

    def type_ids(self) -> list[str]:
        return sorted(self._types)

    async def readiness_for(
        self,
        worker_type_id: str,
        *,
        refresh: bool = False,
    ) -> dict[str, Any]:
        worker_type = self.get(worker_type_id)
        if worker_type is None:
            raise ValueError(f"Unknown worker type: {worker_type_id}")

        ttl_seconds = _readiness_ttl_seconds()
        now = time.monotonic()
        cached = self._readiness_cache.get(worker_type_id)
        if not refresh and cached is not None and now - cached[0] < ttl_seconds:
            return _with_cached(copy.deepcopy(cached[1]), cached=True)

        lock = self._readiness_locks.setdefault(worker_type_id, asyncio.Lock())
        async with lock:
            cached = self._readiness_cache.get(worker_type_id)
            now = time.monotonic()
            if not refresh and cached is not None and now - cached[0] < ttl_seconds:
                return _with_cached(copy.deepcopy(cached[1]), cached=True)
            readiness = await self._probe_readiness(worker_type)
            readiness["ttl_seconds"] = ttl_seconds
            self._readiness_cache[worker_type_id] = (time.monotonic(), copy.deepcopy(readiness))
            return _with_cached(readiness, cached=False)

    async def _probe_readiness(self, worker_type: WorkerType) -> dict[str, Any]:
        family = _worker_family(worker_type.id)
        checks: dict[str, dict[str, Any]] = {
            "launcher": {
                "status": "ok",
                "adapter": _launch_adapter(worker_type.host),
                "reason": None,
            }
        }

        if worker_type.host == "winpc":
            checks.update(await _probe_winpc_launch(worker_type))
        else:
            checks.update(_probe_local_launch(worker_type))

        auth = await _probe_auth(worker_type, family, checks)
        checks["auth"] = auth

        status = "ready"
        reason = None
        for key in ("transport", "wsl", "tmux", "command"):
            check = checks.get(key)
            if check and check["status"] != "ok":
                status = "unavailable"
                reason = check.get("reason")
                break
        if status == "ready" and auth["status"] in {"unauthenticated", "unavailable"}:
            status = "degraded"
            reason = auth.get("reason")

        return {
            "status": status,
            "reason": reason,
            "checked_at": _utc_now(),
            "host": worker_type.host,
            "family": family,
            "checks": checks,
        }


def default_worker_registry(config: AppConfig) -> WorkerTypeRegistry:
    return WorkerTypeRegistry(
        [
            WorkerType(
                id="opencode",
                label="OpenCode",
                description="Start an OpenCode agent session on serrano.",
                command_template=(
                    "/home/danielju/.local/bin/opencode",
                ),
                host="serrano",
                cwd=Path("/home/danielju/Vault"),
            ),
            WorkerType(
                id="claude_code",
                label="Claude Code",
                description="Start a Claude Code agent session on serrano with permissions bypassed.",
                command_template=(
                    "claude", "--dangerously-skip-permissions",
                ),
                host="serrano",
                cwd=Path("/home/danielju"),
            ),
            WorkerType(
                id="codex_cli",
                label="Codex CLI",
                description="Start a Codex CLI agent session on serrano in YOLO mode.",
                command_template=(
                    "codex", "--yolo",
                ),
                host="serrano",
                cwd=Path("/home/danielju"),
            ),
            WorkerType(
                id="gemini_cli",
                label="Gemini CLI",
                description="Start a Gemini CLI agent session on serrano in YOLO mode.",
                command_template=(
                    "gemini", "--yolo",
                ),
                host="serrano",
                cwd=Path("/home/danielju"),
            ),
            WorkerType(
                id="shell",
                label="Shell",
                description="Start a plain bash shell session on serrano.",
                command_template=(
                    "/bin/bash", "--login",
                ),
                host="serrano",
                cwd=Path("/home/danielju"),
            ),
            WorkerType(
                id="winpc_shell",
                label="WinPC Shell",
                description="Start a plain bash shell session in WSL tmux on winpc.",
                command_template=(
                    "/bin/bash", "--login",
                ),
                host="winpc",
                cwd=Path("/home/daniel"),
            ),
            WorkerType(
                id="winpc_opencode",
                label="WinPC OpenCode",
                description="Start an OpenCode agent session in WSL tmux on winpc.",
                command_template=(
                    "/home/daniel/.local/bin/opencode",
                ),
                host="winpc",
                cwd=Path("/home/daniel"),
            ),
            WorkerType(
                id="winpc_claude_code",
                label="WinPC Claude Code",
                description="Start a Claude Code agent session in WSL tmux on winpc with permissions bypassed.",
                command_template=(
                    "claude", "--dangerously-skip-permissions",
                ),
                host="winpc",
                cwd=Path("/home/daniel"),
            ),
            WorkerType(
                id="winpc_codex_cli",
                label="WinPC Codex CLI",
                description="Start a Codex CLI agent session in WSL tmux on winpc in YOLO mode.",
                command_template=(
                    "/home/daniel/.local/bin/codex-wsl", "--yolo",
                ),
                host="winpc",
                cwd=Path("/home/daniel"),
            ),
            WorkerType(
                id="winpc_gemini_cli",
                label="WinPC Gemini CLI",
                description="Start a Gemini CLI agent session in WSL tmux on winpc in YOLO mode.",
                command_template=(
                    "gemini", "--yolo",
                ),
                host="winpc",
                cwd=Path("/home/daniel"),
            ),
        ]
    )


def _with_cached(payload: dict[str, Any], *, cached: bool) -> dict[str, Any]:
    payload["cached"] = cached
    return payload


async def _probe_auth(
    worker_type: WorkerType,
    family: str,
    checks: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    if any(
        checks.get(key, {}).get("status") != "ok"
        for key in ("transport", "wsl", "tmux", "command")
        if key in checks
    ):
        return {
            "status": "unknown",
            "reason": "Launch prerequisites are unavailable, so auth was not checked",
        }
    if family == "shell":
        return {
            "status": "not_applicable",
            "reason": "Shell workers do not require a CLI sign-in probe",
        }
    if family == "opencode":
        return {
            "status": "unknown",
            "reason": "OpenCode does not expose a cheap noninteractive auth probe",
        }
    if family == "gemini":
        return {
            "status": "unknown",
            "reason": "Gemini CLI does not expose a cheap noninteractive auth probe",
        }

    if worker_type.host == "winpc":
        if family == "codex":
            result = await _run_probe(
                _winpc_probe_command("codex --version && codex login status")
            )
            return _codex_auth_result(result)
        if family == "claude":
            result = await _run_probe(
                _winpc_probe_command("claude --version && claude auth status")
            )
            return _claude_auth_result(result)
    else:
        if family == "codex":
            result = await _run_probe(
                ("/bin/bash", "--login", "-lc", "codex --version && codex login status"),
                env=_probe_env(),
            )
            return _codex_auth_result(result)
        if family == "claude":
            result = await _run_probe(
                ("/bin/bash", "--login", "-lc", "claude --version && claude auth status"),
                env=_probe_env(),
            )
            return _claude_auth_result(result)

    return {"status": "unknown", "reason": "No auth probe is configured for this worker type"}


def _probe_local_launch(worker_type: WorkerType) -> dict[str, dict[str, Any]]:
    tmux_ok = Path("/usr/bin/tmux").exists() and os.access("/usr/bin/tmux", os.X_OK)
    tmux = {
        "status": "ok" if tmux_ok else "unavailable",
        "reason": None if tmux_ok else "tmux is not installed at /usr/bin/tmux",
    }
    command = _local_command_check(worker_type.command_template[0])
    return {
        "transport": {"status": "ok", "reason": None},
        "tmux": tmux,
        "command": command,
    }


async def _probe_winpc_launch(worker_type: WorkerType) -> dict[str, dict[str, Any]]:
    marker_prefix = "__DELAMAIN_CHECK__:"
    script = (
        "if ! command -v tmux >/dev/null 2>&1; then "
        f"printf '{marker_prefix}tmux_missing\\n'; exit 22; fi; "
        f"if ! {_remote_command_test(worker_type.command_template[0])}; then "
        f"printf '{marker_prefix}command_missing\\n'; exit 23; fi; "
        f"printf '{marker_prefix}resolved=%s\\n' "
        f"$({_remote_command_resolve(worker_type.command_template[0])})"
    )
    result = await _run_probe(_winpc_probe_command(script))
    stdout = result["stdout"]
    stderr = result["stderr"]
    marker = next(
        (line.strip() for line in stdout.splitlines() if line.startswith(marker_prefix)),
        None,
    )

    transport = {"status": "ok", "reason": None}
    wsl = {"status": "ok", "reason": None}
    tmux = {"status": "ok", "reason": None}
    command = {"status": "ok", "reason": None, "resolved": None}

    if result["exit_code"] == 0 and marker:
        if marker.startswith(marker_prefix + "resolved="):
            command["resolved"] = marker.split("=", 1)[1] or None
        return {
            "transport": transport,
            "wsl": wsl,
            "tmux": tmux,
            "command": command,
        }

    detail = _first_non_empty(stderr, stdout)
    lower = detail.lower()
    if _is_winpc_transport_error(lower):
        reason = detail or "SSH to winpc is unavailable"
        transport = {"status": "unavailable", "reason": f"WinPC SSH unavailable: {reason}"}
        wsl = {"status": "unknown", "reason": "WSL was not checked because SSH is unavailable"}
        tmux = {"status": "unknown", "reason": "tmux was not checked because SSH is unavailable"}
        command = {"status": "unknown", "reason": "Command availability was not checked because SSH is unavailable"}
    elif _is_winpc_wsl_error(lower):
        reason = detail or "WSL is unavailable on winpc"
        wsl = {"status": "unavailable", "reason": f"WinPC WSL unavailable: {reason}"}
        tmux = {"status": "unknown", "reason": "tmux was not checked because WSL is unavailable"}
        command = {"status": "unknown", "reason": "Command availability was not checked because WSL is unavailable"}
    elif marker == marker_prefix + "tmux_missing":
        tmux = {"status": "unavailable", "reason": "tmux is not installed in WinPC WSL"}
        command = {"status": "unknown", "reason": "Command availability was not checked because tmux is unavailable"}
    elif marker == marker_prefix + "command_missing":
        command = {
            "status": "unavailable",
            "reason": f"Worker command is not available in WinPC WSL: {worker_type.command_template[0]}",
        }
    else:
        reason = detail or "Failed to probe WinPC worker readiness"
        command = {"status": "unknown", "reason": reason}
        tmux = {"status": "unknown", "reason": reason}

    return {
        "transport": transport,
        "wsl": wsl,
        "tmux": tmux,
        "command": command,
    }


def _local_command_check(command: str) -> dict[str, Any]:
    if Path(command).is_absolute():
        exists = Path(command).exists() and os.access(command, os.X_OK)
        return {
            "status": "ok" if exists else "unavailable",
            "resolved": command if exists else None,
            "reason": None if exists else f"Executable is missing or not executable: {command}",
        }
    resolved = shutil.which(command, path=_probe_path())
    return {
        "status": "ok" if resolved else "unavailable",
        "resolved": resolved,
        "reason": None if resolved else f"Command is not on PATH: {command}",
    }


def _worker_family(worker_type_id: str) -> str:
    if "codex" in worker_type_id:
        return "codex"
    if "claude" in worker_type_id:
        return "claude"
    if "gemini" in worker_type_id:
        return "gemini"
    if "opencode" in worker_type_id:
        return "opencode"
    if "shell" in worker_type_id:
        return "shell"
    return "unknown"


def _launch_adapter(host: str) -> str:
    if host == "winpc":
        return "ssh_wsl_tmux"
    return "tmux"


async def _run_probe(
    argv: tuple[str, ...],
    *,
    timeout_seconds: float = READINESS_TIMEOUT_SECONDS,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    started = time.monotonic()
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_seconds)
        return {
            "exit_code": proc.returncode,
            "stdout": stdout.decode("utf-8", errors="replace"),
            "stderr": stderr.decode("utf-8", errors="replace"),
            "duration_ms": int((time.monotonic() - started) * 1000),
        }
    except asyncio.TimeoutError:
        return {
            "exit_code": None,
            "stdout": "",
            "stderr": f"Timed out after {timeout_seconds}s",
            "duration_ms": int((time.monotonic() - started) * 1000),
        }
    except OSError as exc:
        return {
            "exit_code": None,
            "stdout": "",
            "stderr": f"{type(exc).__name__}: {exc}",
            "duration_ms": int((time.monotonic() - started) * 1000),
        }


def _codex_auth_result(result: dict[str, Any]) -> dict[str, Any]:
    text = result["stdout"] + result["stderr"]
    if result["exit_code"] is None:
        return {
            "status": "unavailable",
            "reason": _first_non_empty(result["stderr"], result["stdout"]) or "Codex auth probe failed",
            "duration_ms": result["duration_ms"],
        }
    lower = text.lower()
    authenticated = "logged in" in lower and "not logged in" not in lower
    return {
        "status": "authenticated" if authenticated else "unauthenticated",
        "reason": None if authenticated else (_first_non_empty(text) or "Codex CLI is not logged in"),
        "auth_method": _line_containing(text, "Logged in using"),
        "version": _first_non_empty(result["stdout"]),
        "duration_ms": result["duration_ms"],
    }


def _claude_auth_result(result: dict[str, Any]) -> dict[str, Any]:
    if result["exit_code"] is None:
        return {
            "status": "unavailable",
            "reason": _first_non_empty(result["stderr"], result["stdout"]) or "Claude auth probe failed",
            "duration_ms": result["duration_ms"],
        }
    parsed = _last_json_object(result["stdout"])
    if not parsed:
        return {
            "status": "unavailable",
            "reason": _first_non_empty(result["stderr"], result["stdout"]) or "Claude auth probe returned no usable JSON",
            "duration_ms": result["duration_ms"],
        }
    authenticated = bool(parsed.get("loggedIn"))
    return {
        "status": "authenticated" if authenticated else "unauthenticated",
        "reason": None if authenticated else "Claude Code is not signed in",
        "auth_method": parsed.get("authMethod"),
        "account": parsed.get("email"),
        "subscription_type": parsed.get("subscriptionType"),
        "api_provider": parsed.get("apiProvider"),
        "version": _first_non_empty(result["stdout"]),
        "duration_ms": result["duration_ms"],
    }


def _probe_env() -> dict[str, str]:
    env = dict(os.environ)
    env.setdefault("LANG", "C.UTF-8")
    env.setdefault("LC_ALL", "C.UTF-8")
    env.setdefault("PATH", _probe_path())
    env.setdefault("TZ", "America/New_York")
    return env


def _probe_path() -> str:
    return (
        os.environ.get("PATH")
        or "/home/danielju/.npm-global/bin:/home/danielju/.local/bin:/usr/local/bin:/usr/bin:/bin"
    )


def _readiness_ttl_seconds() -> float:
    raw = os.environ.get("DELAMAIN_WORKER_READINESS_TTL_SECONDS")
    if not raw:
        return READINESS_TTL_SECONDS
    try:
        return max(0.0, float(raw))
    except ValueError:
        return READINESS_TTL_SECONDS


def _winpc_probe_command(command: str) -> tuple[str, ...]:
    return (
        "/usr/bin/ssh",
        "-T",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=5",
        "-o",
        "ServerAliveInterval=15",
        "-o",
        "ServerAliveCountMax=2",
        "winpc",
        _winpc_shell_command(command),
    )


def _winpc_shell_command(command: str) -> str:
    return " ".join(("wsl.exe", "-e", "sh", "-lc", _quote_remote_arg(command)))


def _remote_command_test(command: str) -> str:
    if command.startswith("/"):
        return f"[ -x {_quote_remote_arg(command)} ]"
    return f"command -v {_quote_remote_arg(command)} >/dev/null 2>&1"


def _remote_command_resolve(command: str) -> str:
    if command.startswith("/"):
        return f"printf %s {_quote_remote_arg(command)}"
    return f"command -v {_quote_remote_arg(command)}"


def _quote_remote_arg(arg: str) -> str:
    if all(ch.isalnum() or ch in "-_./:" for ch in arg):
        return arg
    return "'" + arg.replace("'", "'\"'\"'") + "'"


def _is_winpc_transport_error(detail: str) -> bool:
    return any(
        token in detail
        for token in (
            "could not resolve hostname",
            "name or service not known",
            "no route to host",
            "connection refused",
            "connection timed out",
            "connection reset",
            "permission denied",
            "host key verification failed",
        )
    )


def _is_winpc_wsl_error(detail: str) -> bool:
    return "wsl" in detail and any(
        token in detail
        for token in (
            "not found",
            "not recognized",
            "failed to translate",
            "no such file",
        )
    )


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _first_non_empty(*texts: str) -> str | None:
    for text in texts:
        for line in text.splitlines():
            stripped = line.strip()
            if stripped:
                return stripped
    return None


def _line_containing(text: str, needle: str) -> str | None:
    for line in text.splitlines():
        if needle in line:
            return line.strip()
    return None


def _last_json_object(text: str) -> dict[str, Any]:
    decoder = json.JSONDecoder()
    last: dict[str, Any] = {}
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            parsed, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            last = parsed
    return last
