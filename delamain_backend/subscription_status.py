from __future__ import annotations

import json
import os
import platform
import socket
import subprocess
import time
from datetime import UTC, datetime
from typing import Any

from delamain_backend.config import AppConfig

STATUS_TTL_SECONDS = 60.0
COMMAND_TIMEOUT_SECONDS = 5.0

_CACHE: tuple[float, dict[str, Any]] | None = None


def subscription_status(config: AppConfig, *, force_refresh: bool = False) -> dict[str, Any]:
    del config
    now = time.monotonic()
    if not force_refresh and _CACHE is not None and now - _CACHE[0] < _ttl_seconds():
        return _CACHE[1]

    payload = {
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "ttl_seconds": _ttl_seconds(),
        "providers": {
            "codex": _provider("codex", "Codex", [_local_codex(), _winpc_codex()]),
            "claude": _provider("claude", "Claude Code", [_local_claude(), _winpc_claude()]),
        },
    }
    globals()["_CACHE"] = (now, payload)
    return payload


def _provider(provider: str, label: str, hosts: list[dict[str, Any]]) -> dict[str, Any]:
    ok_hosts = [host for host in hosts if host["status"] == "ok"]
    degraded_hosts = [host for host in hosts if host["status"] == "degraded"]
    if ok_hosts:
        aggregate_status = "ok"
    elif degraded_hosts:
        aggregate_status = "degraded"
    else:
        aggregate_status = "unavailable"
    return {
        "provider": provider,
        "label": label,
        "billing_kind": "subscription_auth",
        "aggregate_status": aggregate_status,
        "hosts": hosts,
    }


def _local_codex() -> dict[str, Any]:
    result = _run(("/bin/bash", "--login", "-lc", "codex --version && codex login status"))
    return _codex_result("local", result)


def _local_claude() -> dict[str, Any]:
    result = _run(("/bin/bash", "--login", "-lc", "claude --version && claude auth status"))
    return _claude_result("local", result)


def _winpc_codex() -> dict[str, Any]:
    result = _run(
        (
            "/usr/bin/ssh",
            "winpc",
            'wsl.exe -e bash --login -lc "codex --version && codex login status"',
        )
    )
    return _codex_result("winpc", result)


def _winpc_claude() -> dict[str, Any]:
    result = _run(
        (
            "/usr/bin/ssh",
            "winpc",
            'wsl.exe -e bash --login -lc "claude --version && claude auth status"',
        )
    )
    return _claude_result("winpc", result)


def _codex_result(host: str, result: dict[str, Any]) -> dict[str, Any]:
    text = result["stdout"] + result["stderr"]
    authenticated = "Logged in" in text
    status = "ok" if result["exit_code"] == 0 and authenticated else "degraded"
    if result["exit_code"] is None:
        status = "unavailable"
    return {
        **_base_host(host, "codex login status", result, status),
        "authenticated": authenticated if result["exit_code"] == 0 else None,
        "auth_method": _line_containing(text, "Logged in using"),
        "subscription_type": None,
        "account": None,
        "version": _first_line(result["stdout"]),
        "detail": _detail(text, status),
    }


def _claude_result(host: str, result: dict[str, Any]) -> dict[str, Any]:
    stdout = result["stdout"]
    parsed = _last_json_object(stdout)
    authenticated = parsed.get("loggedIn") if parsed else None
    subscription_type = parsed.get("subscriptionType") if parsed else None
    status = "ok" if result["exit_code"] == 0 and authenticated else "degraded"
    if result["exit_code"] is None:
        status = "unavailable"
    return {
        **_base_host(host, "claude auth status", result, status),
        "authenticated": authenticated,
        "auth_method": parsed.get("authMethod") if parsed else None,
        "subscription_type": subscription_type,
        "account": parsed.get("email") if parsed else None,
        "organization": parsed.get("orgName") if parsed else None,
        "api_provider": parsed.get("apiProvider") if parsed else None,
        "version": _first_line(stdout),
        "detail": _detail(result["stdout"] + result["stderr"], status),
    }


def _base_host(
    host: str,
    command: str,
    result: dict[str, Any],
    status: str,
) -> dict[str, Any]:
    return {
        "host": host,
        "local_hostname": socket.gethostname() if host == "local" else None,
        "local_platform": platform.system().lower() if host == "local" else None,
        "command": command,
        "status": status,
        "exit_code": result["exit_code"],
        "duration_ms": result["duration_ms"],
        "checked_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }


def _run(argv: tuple[str, ...]) -> dict[str, Any]:
    started = time.monotonic()
    try:
        completed = subprocess.run(
            argv,
            text=True,
            capture_output=True,
            timeout=COMMAND_TIMEOUT_SECONDS,
            env=_env(),
        )
        return {
            "exit_code": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "duration_ms": int((time.monotonic() - started) * 1000),
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "exit_code": None,
            "stdout": exc.stdout or "",
            "stderr": (exc.stderr or "") + f"\nTimed out after {COMMAND_TIMEOUT_SECONDS}s",
            "duration_ms": int((time.monotonic() - started) * 1000),
        }
    except OSError as exc:
        return {
            "exit_code": None,
            "stdout": "",
            "stderr": f"{type(exc).__name__}: {exc}",
            "duration_ms": int((time.monotonic() - started) * 1000),
        }


def _env() -> dict[str, str]:
    env = dict(os.environ)
    env.setdefault("HOME", str(os.environ.get("HOME", "")))
    env.setdefault("LANG", "C.UTF-8")
    env.setdefault("LC_ALL", "C.UTF-8")
    env.setdefault(
        "PATH",
        "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/home/daniel/.local/bin",
    )
    env.setdefault("TZ", "America/New_York")
    return env


def _ttl_seconds() -> float:
    raw = os.environ.get("DELAMAIN_SUBSCRIPTION_STATUS_TTL_SECONDS")
    if not raw:
        return STATUS_TTL_SECONDS
    try:
        return max(0.0, float(raw))
    except ValueError:
        return STATUS_TTL_SECONDS


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


def _first_line(text: str) -> str | None:
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


def _detail(text: str, status: str) -> str | None:
    if status == "ok":
        return None
    return text.strip()[:1000] or "Status command did not return usable auth data"
