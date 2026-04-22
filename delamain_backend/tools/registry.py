from __future__ import annotations

import asyncio
import json
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
                output_limit=config.tools.output_limit_bytes,
            ),
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
    data = decision.path.read_bytes()
    truncated = len(data) > output_limit
    text = data[:output_limit].decode("utf-8")
    return {
        "status": "success",
        "path": str(decision.path),
        "root": decision.root_name,
        "stdout": text,
        "stderr": "",
        "duration_ms": int((time.monotonic() - start) * 1000),
        "byte_count": len(data),
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
