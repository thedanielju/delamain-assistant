from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shlex
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from delamain_backend.config import AppConfig
from delamain_backend.errors import SensitiveLocked, ToolExecutionError, ToolPolicyDenied
from delamain_backend.security import PathPolicy

ToolHandler = Callable[[dict[str, Any], "ToolExecutionContext"], Awaitable[dict[str, Any]]]


@dataclass(frozen=True)
class ToolExecutionContext:
    conversation_id: str | None = None
    run_id: str | None = None
    sensitive_unlocked: bool = False


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: ToolHandler
    approval_policy_default: str = "auto"
    risk: str = "low"

    def chat_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def responses_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, definition: ToolDefinition) -> None:
        self._tools[definition.name] = definition

    def schemas(
        self, api_family: str, disabled_tools: set[str] | None = None
    ) -> list[dict[str, Any]]:
        disabled_tools = disabled_tools or set()
        tools = [
            tool
            for tool in self._tools.values()
            if tool.name not in disabled_tools
        ]
        if api_family == "responses":
            return [tool.responses_schema() for tool in tools]
        return [tool.chat_schema() for tool in tools]

    def has_tool(self, name: str) -> bool:
        return name in self._tools

    def tool_names(self) -> list[str]:
        return sorted(self._tools)

    def metadata(self) -> list[dict[str, Any]]:
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "approval_policy_default": tool.approval_policy_default,
                "risk": tool.risk,
            }
            for tool in sorted(self._tools.values(), key=lambda item: item.name)
        ]

    def approval_policy_default(self, name: str) -> str:
        tool = self._tools.get(name)
        return tool.approval_policy_default if tool else "auto"

    async def execute(
        self,
        name: str,
        arguments: dict[str, Any],
        context: ToolExecutionContext | None = None,
    ) -> dict[str, Any]:
        definition = self._tools.get(name)
        if definition is None:
            raise ToolPolicyDenied(f"Unknown tool: {name}")
        return await definition.handler(arguments, context or ToolExecutionContext())


def default_tool_registry(config: AppConfig) -> ToolRegistry:
    registry = ToolRegistry()
    policy = PathPolicy(config)
    registry.register(
        ToolDefinition(
            name="get_now",
            description="Return Daniel's live wall-clock time.",
            parameters={"type": "object", "properties": {}, "additionalProperties": False},
            handler=lambda args, ctx: _run_helper(
                [str(config.paths.llm_workspace / "bin" / "now")],
                timeout=config.tools.default_timeout_seconds,
                output_limit=config.tools.output_limit_bytes,
            ),
        )
    )
    registry.register(
        ToolDefinition(
            name="delamain_ref",
            description="Return reference-ingestion helper status.",
            parameters={
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
            handler=lambda args, ctx: _run_helper(
                [str(config.paths.llm_workspace / "bin" / "delamain-ref"), "status", "--json"],
                timeout=config.tools.default_timeout_seconds,
                output_limit=config.tools.output_limit_bytes,
            ),
        )
    )
    registry.register(
        ToolDefinition(
            name="delamain_vault_index",
            description="Return vault-index helper status.",
            parameters={
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
            handler=lambda args, ctx: _run_helper(
                [
                    str(config.paths.llm_workspace / "bin" / "delamain-vault-index"),
                    "status",
                    "--json",
                ],
                timeout=config.tools.default_timeout_seconds,
                output_limit=config.tools.output_limit_bytes,
            ),
        )
    )
    registry.register(
        ToolDefinition(
            name="read_text_file",
            description="Read a UTF-8 text file from allowed DELAMAIN roots.",
            parameters={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
                "additionalProperties": False,
            },
            handler=lambda args, ctx: _read_text_file(
                args,
                ctx,
                policy=policy,
                output_limit=config.tools.output_limit_bytes,
            ),
        )
    )
    registry.register(
        ToolDefinition(
            name="list_directory",
            description="List a directory from allowed DELAMAIN roots, omitting restricted entries.",
            parameters={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
                "additionalProperties": False,
            },
            handler=lambda args, ctx: _list_directory(args, ctx, policy=policy),
        )
    )
    registry.register(
        ToolDefinition(
            name="search_vault",
            description="Search text files under the non-Sensitive Vault root.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 50},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
            handler=lambda args, ctx: _search_vault(
                args,
                ctx,
                policy=policy,
                vault_root=config.paths.vault,
                vault_index_helper=config.paths.llm_workspace / "bin" / "delamain-vault-index",
                output_limit=config.tools.output_limit_bytes,
            ),
        )
    )
    registry.register(
        ToolDefinition(
            name="patch_text_file",
            description=(
                "Replace one exact UTF-8 text span in an allowed text file. "
                "Sensitive files require the conversation's Sensitive unlock. "
                "Creates a runtime backup before writing."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "old_text": {"type": "string"},
                    "new_text": {"type": "string"},
                    "expected_sha256": {"type": "string"},
                },
                "required": ["path", "old_text", "new_text"],
                "additionalProperties": False,
            },
            handler=lambda args, ctx: _patch_text_file(
                args,
                ctx,
                policy=policy,
                backup_root=config.database.path.parent / "tool-backups",
                output_limit=config.tools.output_limit_bytes,
            ),
            risk="write",
        )
    )
    registry.register(
        ToolDefinition(
            name="run_shell",
            description=(
                "Run a bounded command using structured argv and an allowed cwd. "
                "Raw shell strings, Sensitive paths, and inherited secret env are not allowed."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "argv": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 1,
                        "maxItems": 32,
                    },
                    "cwd": {"type": "string"},
                    "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 60},
                },
                "required": ["argv", "cwd"],
                "additionalProperties": False,
            },
            handler=lambda args, ctx: _run_shell(
                args,
                policy=policy,
                allowed_cwd_roots=(
                    config.paths.vault,
                    config.paths.llm_workspace,
                    Path(__file__).resolve().parents[2],
                ),
                sensitive_root=config.paths.sensitive,
                default_timeout=config.tools.default_timeout_seconds,
                output_limit=config.tools.output_limit_bytes,
            ),
            risk="shell",
        )
    )
    registry.register(
        ToolDefinition(
            name="get_health_status",
            description="Return basic deterministic DELAMAIN backend helper/path health.",
            parameters={"type": "object", "properties": {}, "additionalProperties": False},
            handler=lambda args, ctx: _get_health_status(
                config,
                timeout=config.tools.default_timeout_seconds,
                output_limit=config.tools.output_limit_bytes,
            ),
        )
    )
    return registry


async def _patch_text_file(
    args: dict[str, Any],
    context: ToolExecutionContext,
    *,
    policy: PathPolicy,
    backup_root: Path,
    output_limit: int,
) -> dict[str, Any]:
    start = time.monotonic()
    raw_path = _required_string(args, "path")
    old_text = _required_string(args, "old_text")
    new_text = args.get("new_text")
    if not isinstance(new_text, str):
        raise ToolPolicyDenied("Missing required string argument: new_text")
    expected_sha256 = args.get("expected_sha256")
    if expected_sha256 is not None and not isinstance(expected_sha256, str):
        raise ToolPolicyDenied("expected_sha256 must be a string when provided")
    decision = policy.check(
        raw_path,
        operation="write",
        sensitive_unlocked=context.sensitive_unlocked,
    )
    if not decision.path.is_file():
        raise ToolPolicyDenied(f"Path is not a file: {decision.path}")
    original_bytes = decision.path.read_bytes()
    original_sha = hashlib.sha256(original_bytes).hexdigest()
    if expected_sha256 and expected_sha256 != original_sha:
        raise ToolPolicyDenied("File sha256 did not match expected_sha256")
    original_text = original_bytes.decode("utf-8", errors="strict")
    occurrences = original_text.count(old_text)
    if occurrences != 1:
        raise ToolPolicyDenied(
            f"old_text must match exactly once; matched {occurrences} times"
        )
    updated_text = original_text.replace(old_text, new_text, 1)
    backup_path = _write_tool_backup(
        source_path=decision.path,
        content=original_bytes,
        backup_root=backup_root,
    )
    decision.path.write_text(updated_text, encoding="utf-8")
    updated_bytes = updated_text.encode("utf-8")
    stdout_payload = {
        "path": str(decision.path),
        "backup_path": str(backup_path),
        "old_sha256": original_sha,
        "new_sha256": hashlib.sha256(updated_bytes).hexdigest(),
        "old_byte_count": len(original_bytes),
        "new_byte_count": len(updated_bytes),
    }
    stdout_raw = json.dumps(stdout_payload, sort_keys=True)
    encoded = stdout_raw.encode("utf-8")
    truncated = len(encoded) > output_limit
    return {
        "status": "success",
        "path": str(decision.path),
        "root": decision.root_name,
        "stdout": encoded[:output_limit].decode("utf-8", errors="replace"),
        "stderr": "",
        "duration_ms": int((time.monotonic() - start) * 1000),
        "backup_path": str(backup_path),
        "truncated": truncated,
    }


async def _run_shell(
    args: dict[str, Any],
    *,
    policy: PathPolicy,
    allowed_cwd_roots: tuple[Path, ...],
    sensitive_root: Path,
    default_timeout: int,
    output_limit: int,
) -> dict[str, Any]:
    start = time.monotonic()
    argv = _required_string_list(args, "argv")
    raw_cwd = _required_string(args, "cwd")
    timeout = int(args.get("timeout_seconds") or min(default_timeout, 60))
    if timeout < 1 or timeout > 60:
        raise ToolPolicyDenied("timeout_seconds must be between 1 and 60")
    executable = Path(argv[0]).expanduser()
    if not executable.is_absolute():
        raise ToolPolicyDenied("run_shell argv[0] must be an absolute executable path")
    if executable.name in {"sh", "bash", "zsh", "fish", "dash"} and any(
        arg == "-c" or (arg.startswith("-") and "c" in arg) for arg in argv[1:]
    ):
        raise ToolPolicyDenied("run_shell does not allow shell -c command strings")
    cwd_decision = policy.check(
        raw_cwd,
        operation="shell",
        sensitive_unlocked=False,
        allow_binary=True,
    )
    if cwd_decision.sensitive:
        raise ToolPolicyDenied("Sensitive paths are not allowed as run_shell cwd")
    if not cwd_decision.path.is_dir():
        raise ToolPolicyDenied(f"run_shell cwd is not a directory: {cwd_decision.path}")
    if not _inside_any(cwd_decision.path, allowed_cwd_roots):
        raise ToolPolicyDenied(f"run_shell cwd is outside allowed roots: {cwd_decision.path}")
    for arg in argv:
        if _argument_targets_sensitive(arg, cwd_decision.path, sensitive_root):
            raise ToolPolicyDenied("Sensitive paths are not allowed in run_shell argv")

    stdout = b""
    stderr = b""
    timed_out = False
    exit_code: int | None = None
    try:
        process = await asyncio.create_subprocess_exec(
            *argv,
            cwd=str(cwd_decision.path),
            env=_minimal_env(),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
            exit_code = process.returncode
        except asyncio.TimeoutError:
            timed_out = True
            process.kill()
            stdout, stderr = await process.communicate()
            exit_code = process.returncode
            stderr += f"\nTimed out after {timeout}s\n".encode("utf-8")
    except FileNotFoundError as exc:
        stderr = str(exc).encode("utf-8")
    except OSError as exc:
        stderr = f"{type(exc).__name__}: {exc}".encode("utf-8")

    truncated = len(stdout) > output_limit or len(stderr) > output_limit
    status = "timeout" if timed_out else ("success" if exit_code == 0 else "failed")
    return {
        "status": status,
        "returncode": exit_code,
        "stdout": stdout[:output_limit].decode("utf-8", errors="replace"),
        "stderr": stderr[:output_limit].decode("utf-8", errors="replace"),
        "duration_ms": int((time.monotonic() - start) * 1000),
        "truncated": truncated,
    }


async def _read_text_file(
    args: dict[str, Any],
    context: ToolExecutionContext,
    *,
    policy: PathPolicy,
    output_limit: int,
) -> dict[str, Any]:
    start = time.monotonic()
    raw_path = _required_string(args, "path")
    decision = policy.check(
        raw_path,
        operation="read",
        sensitive_unlocked=context.sensitive_unlocked,
    )
    if not decision.path.is_file():
        raise ToolPolicyDenied(f"Path is not a file: {decision.path}")
    size = decision.path.stat().st_size
    with decision.path.open("rb") as file:
        data = file.read(output_limit + 1)
    truncated = size > output_limit or len(data) > output_limit
    text = data[:output_limit].decode("utf-8", errors="replace")
    return {
        "status": "success",
        "path": str(decision.path),
        "root": decision.root_name,
        "stdout": text,
        "stderr": "",
        "duration_ms": int((time.monotonic() - start) * 1000),
        "byte_count": size,
        "truncated": truncated,
    }


async def _list_directory(
    args: dict[str, Any],
    context: ToolExecutionContext,
    *,
    policy: PathPolicy,
) -> dict[str, Any]:
    start = time.monotonic()
    raw_path = _required_string(args, "path")
    decision = policy.check(
        raw_path,
        operation="list",
        sensitive_unlocked=context.sensitive_unlocked,
        allow_binary=True,
    )
    if not decision.path.is_dir():
        raise ToolPolicyDenied(f"Path is not a directory: {decision.path}")
    entries: list[dict[str, Any]] = []
    omitted = 0
    for child in sorted(decision.path.iterdir(), key=lambda item: item.name.lower()):
        try:
            resolved = child.resolve(strict=True)
        except OSError:
            omitted += 1
            continue
        try:
            child_decision = policy.check(
                str(resolved),
                operation="list",
                sensitive_unlocked=context.sensitive_unlocked,
                allow_binary=True,
            )
        except (ToolPolicyDenied, SensitiveLocked):
            omitted += 1
            continue
        entries.append(
            {
                "name": child.name,
                "path": str(child_decision.path),
                "type": "directory" if child_decision.path.is_dir() else "file",
            }
        )
    stdout = json.dumps({"entries": entries, "omitted_restricted": omitted}, sort_keys=True)
    return {
        "status": "success",
        "path": str(decision.path),
        "root": decision.root_name,
        "stdout": stdout,
        "stderr": "",
        "duration_ms": int((time.monotonic() - start) * 1000),
        "entry_count": len(entries),
        "omitted_restricted": omitted,
        "truncated": False,
    }


async def _search_vault(
    args: dict[str, Any],
    context: ToolExecutionContext,
    *,
    policy: PathPolicy,
    vault_root: Path,
    vault_index_helper: Path,
    output_limit: int,
) -> dict[str, Any]:
    start = time.monotonic()
    query = _required_string(args, "query")
    limit = int(args.get("limit") or 20)
    if limit < 1 or limit > 50:
        raise ToolPolicyDenied("search_vault limit must be between 1 and 50")
    decision = policy.check(
        str(vault_root),
        operation="search",
        sensitive_unlocked=context.sensitive_unlocked,
        allow_binary=True,
    )
    indexed = await _search_vault_index(
        query=query,
        limit=limit,
        policy=policy,
        sensitive_unlocked=context.sensitive_unlocked,
        vault_root=decision.path,
        helper=vault_index_helper,
        output_limit=output_limit,
    )
    if indexed is not None:
        indexed["duration_ms"] = int((time.monotonic() - start) * 1000)
        return indexed

    results: list[dict[str, Any]] = []
    lowered = query.lower()
    for path in sorted(decision.path.rglob("*")):
        if len(results) >= limit:
            break
        if not path.is_file():
            continue
        resolved = path.resolve(strict=True)
        try:
            file_decision = policy.check(
                str(resolved),
                operation="read",
                sensitive_unlocked=context.sensitive_unlocked,
                allow_binary=False,
            )
        except (ToolPolicyDenied, SensitiveLocked):
            continue
        try:
            text = file_decision.path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for line_number, line in enumerate(text.splitlines(), start=1):
            if lowered in line.lower():
                results.append(
                    {
                        "path": str(file_decision.path),
                        "line": line_number,
                        "text": line[:500],
                    }
                )
                break
    raw_stdout = json.dumps({"query": query, "results": results}, sort_keys=True)
    encoded = raw_stdout.encode("utf-8")
    truncated = len(encoded) > output_limit
    stdout = encoded[:output_limit].decode("utf-8", errors="replace")
    return {
        "status": "success",
        "root": "vault",
        "stdout": stdout,
        "stderr": "",
        "duration_ms": int((time.monotonic() - start) * 1000),
        "result_count": len(results),
        "truncated": truncated,
    }


async def _search_vault_index(
    *,
    query: str,
    limit: int,
    policy: PathPolicy,
    sensitive_unlocked: bool,
    vault_root: Path,
    helper: Path,
    output_limit: int,
) -> dict[str, Any] | None:
    if not helper.exists():
        return None
    result = await _run_helper(
        [str(helper), "query", query, "--json"],
        timeout=30,
        output_limit=max(output_limit, 1_000_000),
    )
    if result["status"] != "success" or result.get("truncated"):
        return None
    try:
        payload = json.loads(result["stdout"])
    except json.JSONDecodeError:
        return None
    matches = payload.get("matches")
    if not isinstance(matches, list):
        return None

    results: list[dict[str, Any]] = []
    for match in matches:
        if len(results) >= limit:
            break
        normalized = _normalize_vault_index_match(match)
        rel_path = normalized.get("path")
        if rel_path:
            candidate = vault_root / rel_path
            try:
                decision = policy.check(
                    str(candidate),
                    operation="read",
                    sensitive_unlocked=sensitive_unlocked,
                    allow_binary=False,
                )
            except (ToolPolicyDenied, SensitiveLocked):
                continue
            normalized["path"] = str(decision.path)
        results.append(normalized)

    raw_stdout = json.dumps(
        {"query": query, "source": "vault-index", "results": results},
        sort_keys=True,
    )
    encoded = raw_stdout.encode("utf-8")
    truncated = len(encoded) > output_limit
    stdout = encoded[:output_limit].decode("utf-8", errors="replace")
    return {
        "status": "success",
        "root": "vault",
        "stdout": stdout,
        "stderr": "",
        "result_count": len(results),
        "truncated": truncated,
        "source": "vault-index",
    }


def _normalize_vault_index_match(match: Any) -> dict[str, Any]:
    if not isinstance(match, dict):
        return {"kind": "unknown", "value": str(match)}
    kind = str(match.get("kind") or "unknown")
    value = match.get("value")
    out: dict[str, Any] = {"kind": kind}
    if kind == "note" and isinstance(value, str):
        out["path"] = value
    elif kind == "heading" and isinstance(value, dict):
        out["path"] = value.get("file")
        out["heading"] = value.get("heading")
        out["level"] = value.get("level")
        out["anchor"] = value.get("anchor")
    else:
        out["value"] = value
        if "count" in match:
            out["count"] = match["count"]
    return out


async def _get_health_status(
    config: AppConfig,
    *,
    timeout: int,
    output_limit: int,
) -> dict[str, Any]:
    start = time.monotonic()
    helpers = {
        "now": [str(config.paths.llm_workspace / "bin" / "now")],
        "delamain_ref": [
            str(config.paths.llm_workspace / "bin" / "delamain-ref"),
            "status",
            "--json",
        ],
        "delamain_vault_index": [
            str(config.paths.llm_workspace / "bin" / "delamain-vault-index"),
            "status",
            "--json",
        ],
    }
    helper_results: dict[str, Any] = {}
    for name, argv in helpers.items():
        path = Path(argv[0])
        if not path.exists():
            helper_results[name] = {
                "exists": False,
                "ok": False,
                "error": f"missing: {path}",
            }
            continue
        try:
            result = await _run_helper(argv, timeout=timeout, output_limit=output_limit)
        except Exception as exc:
            helper_results[name] = {
                "exists": True,
                "ok": False,
                "error": str(exc),
            }
            continue
        helper_results[name] = {
            "exists": True,
            "ok": result["status"] == "success",
            "returncode": result.get("returncode"),
            "truncated": result.get("truncated", False),
        }

    paths = {
        "vault": str(config.paths.vault),
        "llm_workspace": str(config.paths.llm_workspace),
        "sensitive": str(config.paths.sensitive),
        "sqlite": str(config.database.path),
    }
    path_results = {
        name: {"path": path, "exists": Path(path).exists()}
        for name, path in paths.items()
    }
    payload = {
        "status": "ok"
        if all(item["ok"] for item in helper_results.values())
        and path_results["vault"]["exists"]
        and path_results["llm_workspace"]["exists"]
        else "degraded",
        "helpers": helper_results,
        "paths": path_results,
    }
    return {
        "status": "success",
        "stdout": json.dumps(payload, sort_keys=True),
        "stderr": "",
        "duration_ms": int((time.monotonic() - start) * 1000),
        "truncated": False,
    }


async def _run_helper(
    argv: list[str],
    *,
    timeout: int,
    output_limit: int,
) -> dict[str, Any]:
    executable = Path(argv[0])
    if not executable.exists():
        raise ToolExecutionError(f"Helper does not exist: {executable}")
    start = time.monotonic()
    process = await asyncio.create_subprocess_exec(
        *argv,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            process.communicate(), timeout=timeout
        )
    except asyncio.TimeoutError as exc:
        process.kill()
        await process.wait()
        raise ToolExecutionError(f"Tool timed out after {timeout}s") from exc

    stdout = stdout_bytes[:output_limit].decode("utf-8", errors="replace")
    stderr = stderr_bytes[:output_limit].decode("utf-8", errors="replace")
    truncated = len(stdout_bytes) > output_limit or len(stderr_bytes) > output_limit
    return {
        "status": "success" if process.returncode == 0 else "failed",
        "returncode": process.returncode,
        "stdout": stdout,
        "stderr": stderr,
        "duration_ms": int((time.monotonic() - start) * 1000),
        "truncated": truncated,
    }


def _required_string(args: dict[str, Any], key: str) -> str:
    value = args.get(key)
    if not isinstance(value, str) or not value:
        raise ToolPolicyDenied(f"Missing required string argument: {key}")
    return value


def _required_string_list(args: dict[str, Any], key: str) -> list[str]:
    value = args.get(key)
    if not isinstance(value, list) or not value:
        raise ToolPolicyDenied(f"Missing required string array argument: {key}")
    if len(value) > 32:
        raise ToolPolicyDenied(f"{key} can contain at most 32 arguments")
    if not all(isinstance(item, str) and item for item in value):
        raise ToolPolicyDenied(f"{key} must contain non-empty strings")
    return list(value)


def _write_tool_backup(*, source_path: Path, content: bytes, backup_root: Path) -> Path:
    backup_root = backup_root.expanduser().resolve(strict=False)
    safe_name = source_path.name.replace("/", "_") or "file"
    stamp = time.strftime("%Y%m%dT%H%M%S", time.gmtime())
    backup_dir = backup_root / "patch_text_file"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"{safe_name}.{stamp}.{time.time_ns()}.bak"
    backup_path.write_bytes(content)
    return backup_path


def _minimal_env() -> dict[str, str]:
    return {
        "HOME": str(Path.home()),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "LC_ALL": os.environ.get("LC_ALL", "C.UTF-8"),
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "TZ": os.environ.get("TZ", "America/New_York"),
    }


def _argument_targets_sensitive(arg: str, cwd: Path, sensitive_root: Path) -> bool:
    for token in _path_like_tokens(arg):
        expanded = Path(token).expanduser()
        candidate = expanded if expanded.is_absolute() else cwd / expanded
        if _inside(candidate, sensitive_root):
            return True
    return False


def _path_like_tokens(arg: str) -> list[str]:
    candidates = [arg]
    if "=" in arg:
        candidates.append(arg.split("=", 1)[1])
    tokens: list[str] = []
    for candidate in candidates:
        try:
            split_tokens = shlex.split(candidate)
        except ValueError:
            split_tokens = [candidate]
        for token in split_tokens:
            if _looks_path_like(token):
                tokens.append(token)
    return tokens


def _looks_path_like(token: str) -> bool:
    return (
        token.startswith("/")
        or token.startswith("~/")
        or token.startswith("./")
        or token.startswith("../")
        or "/" in token
    )


def _inside(path: Path, root: Path) -> bool:
    resolved = path.expanduser().resolve(strict=False)
    resolved_root = root.expanduser().resolve(strict=False)
    return resolved == resolved_root or resolved_root in resolved.parents


def _inside_any(path: Path, roots: tuple[Path, ...]) -> bool:
    return any(_inside(path, root) for root in roots)
