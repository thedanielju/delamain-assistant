from __future__ import annotations

import asyncio
import json
import os
import shlex
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from delamain_backend.actions.registry import ActionRegistry, ActionSpec
from delamain_backend.config import AppConfig
from delamain_backend.db import Database
from delamain_backend.errors import ToolExecutionError, ToolPolicyDenied
from delamain_backend.events import EventBus

PREVIEW_CHARS = 4000


class ToolTimeout(ToolExecutionError):
    code = "TOOL_TIMEOUT"


@dataclass(frozen=True)
class CommandPolicy:
    allowed_cwd_roots: tuple[Path, ...]
    sensitive_root: Path
    output_root: Path


class ActionRunner:
    def __init__(
        self,
        *,
        config: AppConfig,
        db: Database,
        bus: EventBus | None,
        registry: ActionRegistry,
    ):
        self.config = config
        self.db = db
        self.bus = bus
        self.registry = registry
        self.policy = CommandPolicy(
            allowed_cwd_roots=(
                config.paths.vault,
                config.paths.llm_workspace,
                Path(__file__).resolve().parents[2],
            ),
            sensitive_root=config.paths.sensitive,
            output_root=config.database.path.parent / "action-outputs",
        )
        self._validate_output_root()

    async def execute(
        self,
        action_id: str,
        *,
        conversation_id: str | None = None,
    ) -> dict[str, Any]:
        spec = self.registry.get(action_id)
        if spec is None:
            raise ToolPolicyDenied(f"Unknown action: {action_id}")
        if conversation_id is not None:
            conversation = await self.db.fetchone(
                "SELECT id FROM conversations WHERE id = ?", (conversation_id,)
            )
            if conversation is None:
                raise ToolPolicyDenied(f"Conversation not found: {conversation_id}")

        run_id = f"actionrun_{uuid.uuid4().hex}"
        output_dir = self.policy.output_root / run_id
        output_dir.mkdir(parents=True, exist_ok=False)
        stdout_path = output_dir / "stdout.txt"
        stderr_path = output_dir / "stderr.txt"
        metadata_path = output_dir / "metadata.json"

        try:
            self._validate_spec(spec)
        except Exception as exc:
            await self._persist_started(
                run_id=run_id,
                spec=spec,
                conversation_id=conversation_id,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                metadata_path=metadata_path,
            )
            result = _policy_result(
                run_id=run_id,
                spec=spec,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                metadata_path=metadata_path,
                error_message=str(exc),
            )
            metadata_path.write_text(json.dumps(result, sort_keys=True), encoding="utf-8")
            await self._persist_finished(result)
            await self._audit(
                conversation_id,
                "quick_action.denied",
                f"Quick action {spec.id} denied",
                result,
            )
            raise

        await self._persist_started(
            run_id=run_id,
            spec=spec,
            conversation_id=conversation_id,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            metadata_path=metadata_path,
        )
        await self._audit(
            conversation_id,
            "quick_action.started",
            f"Quick action {spec.id} started",
            {
                "id": run_id,
                "action_id": spec.id,
                "argv": list(spec.argv),
                "cwd": str(spec.cwd),
            },
        )

        result = await self._run_command(
            run_id=run_id,
            spec=spec,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            metadata_path=metadata_path,
        )
        metadata_path.write_text(json.dumps(result, sort_keys=True), encoding="utf-8")
        await self._persist_finished(result)
        action = "quick_action.completed"
        if result["status"] == "timeout":
            action = "quick_action.timeout"
        if result["status"] == "failed":
            action = "quick_action.failed"
        await self._audit(
            conversation_id,
            action,
            f"Quick action {spec.id} {result['status']}",
            result,
        )
        return result

    def _validate_spec(self, spec: ActionSpec) -> None:
        if not spec.argv:
            raise ToolPolicyDenied("Action argv cannot be empty")
        executable = Path(spec.argv[0]).expanduser()
        if not executable.is_absolute():
            raise ToolPolicyDenied("Action executable must be an absolute path")
        cwd = spec.cwd.expanduser().resolve(strict=False)
        if not _inside_any(cwd, self.policy.allowed_cwd_roots):
            raise ToolPolicyDenied(f"Action cwd is outside allowed roots: {cwd}")
        if _inside(cwd, self.policy.sensitive_root):
            raise ToolPolicyDenied("Sensitive paths are not allowed as action cwd")
        for arg in spec.argv:
            if self._argument_targets_sensitive(arg, cwd):
                raise ToolPolicyDenied("Sensitive paths are not allowed in action argv")

    def _validate_output_root(self) -> None:
        output_root = self.policy.output_root.expanduser().resolve(strict=False)
        for root in (
            self.config.paths.vault,
            self.config.paths.llm_workspace,
            self.config.paths.sensitive,
        ):
            if _inside(output_root, root):
                raise ToolPolicyDenied(
                    f"Action output root must be outside synced roots: {output_root}"
                )

    def _argument_targets_sensitive(self, arg: str, cwd: Path) -> bool:
        for token in _path_like_tokens(arg):
            expanded = Path(token).expanduser()
            candidate = expanded if expanded.is_absolute() else cwd / expanded
            if _inside(candidate, self.policy.sensitive_root):
                return True
        return False

    async def _run_command(
        self,
        *,
        run_id: str,
        spec: ActionSpec,
        stdout_path: Path,
        stderr_path: Path,
        metadata_path: Path,
    ) -> dict[str, Any]:
        started = asyncio.get_running_loop().time()
        stdout = b""
        stderr = b""
        timed_out = False
        exit_code: int | None = None
        try:
            process = await asyncio.create_subprocess_exec(
                *spec.argv,
                cwd=str(spec.cwd),
                env=_minimal_env(),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(), timeout=spec.timeout_seconds
                )
                exit_code = process.returncode
            except asyncio.TimeoutError:
                timed_out = True
                process.kill()
                stdout, stderr = await process.communicate()
                exit_code = process.returncode
                stderr += f"\nTimed out after {spec.timeout_seconds}s\n".encode("utf-8")
        except FileNotFoundError as exc:
            exit_code = None
            stderr = str(exc).encode("utf-8")
        except OSError as exc:
            exit_code = None
            stderr = f"{type(exc).__name__}: {exc}".encode("utf-8")
        except Exception as exc:
            exit_code = None
            stderr = f"{type(exc).__name__}: {exc}".encode("utf-8")

        stdout_path.write_bytes(stdout)
        stderr_path.write_bytes(stderr)
        duration_ms = int((asyncio.get_running_loop().time() - started) * 1000)
        status = "timeout" if timed_out else ("success" if exit_code == 0 else "failed")
        error_code = "TOOL_TIMEOUT" if timed_out else None
        if status == "failed" and exit_code is None:
            error_code = "TOOL_EXECUTION_ERROR"
        error_message = None
        if status == "failed":
            error_message = _preview(stderr).strip() or "Action failed"
        return {
            "id": run_id,
            "action_id": spec.id,
            "label": spec.label,
            "status": status,
            "error_code": error_code,
            "error_message": error_message,
            "exit_code": exit_code,
            "duration_ms": duration_ms,
            "argv": list(spec.argv),
            "cwd": str(spec.cwd),
            "writes": spec.writes,
            "remote": spec.remote,
            "stdout_path": str(stdout_path),
            "stderr_path": str(stderr_path),
            "metadata_path": str(metadata_path),
            "stdout_bytes": len(stdout),
            "stderr_bytes": len(stderr),
            "stdout_preview": _preview(stdout),
            "stderr_preview": _preview(stderr),
            "stdout_preview_truncated": len(stdout.decode("utf-8", errors="replace"))
            > PREVIEW_CHARS,
            "stderr_preview_truncated": len(stderr.decode("utf-8", errors="replace"))
            > PREVIEW_CHARS,
        }

    async def _persist_started(
        self,
        *,
        run_id: str,
        spec: ActionSpec,
        conversation_id: str | None,
        stdout_path: Path,
        stderr_path: Path,
        metadata_path: Path,
    ) -> None:
        await self.db.execute(
            """
            INSERT INTO action_runs(
                id, conversation_id, action_id, label, argv_json, cwd,
                status, writes, remote, stdout_path, stderr_path, metadata_path
            )
            VALUES (?, ?, ?, ?, ?, ?, 'started', ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                conversation_id,
                spec.id,
                spec.label,
                json.dumps(list(spec.argv), sort_keys=True),
                str(spec.cwd),
                1 if spec.writes else 0,
                1 if spec.remote else 0,
                str(stdout_path),
                str(stderr_path),
                str(metadata_path),
            ),
        )

    async def _persist_finished(self, result: dict[str, Any]) -> None:
        await self.db.execute(
            """
            UPDATE action_runs
            SET status = ?,
                exit_code = ?,
                duration_ms = ?,
                stdout_preview = ?,
                stderr_preview = ?,
                stdout_bytes = ?,
                stderr_bytes = ?,
                error_code = ?,
                error_message = ?,
                completed_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            WHERE id = ?
            """,
            (
                result["status"],
                result.get("exit_code"),
                result.get("duration_ms"),
                result.get("stdout_preview"),
                result.get("stderr_preview"),
                result.get("stdout_bytes"),
                result.get("stderr_bytes"),
                result.get("error_code"),
                result.get("error_message"),
                result["id"],
            ),
        )

    async def _audit(
        self,
        conversation_id: str | None,
        action: str,
        summary: str,
        result: dict[str, Any],
    ) -> None:
        if self.bus is None or conversation_id is None:
            return
        await self.bus.emit(
            conversation_id=conversation_id,
            run_id=None,
            event_type="audit",
            payload={
                "action": action,
                "summary": summary,
                "action_id": result.get("action_id"),
                "action_run_id": result.get("id"),
                "status": result.get("status"),
                "exit_code": result.get("exit_code"),
                "duration_ms": result.get("duration_ms"),
                "writes": result.get("writes"),
                "remote": result.get("remote"),
            },
        )


def _policy_result(
    *,
    run_id: str,
    spec: ActionSpec,
    stdout_path: Path,
    stderr_path: Path,
    metadata_path: Path,
    error_message: str,
) -> dict[str, Any]:
    stderr_path.write_text(error_message, encoding="utf-8")
    stdout_path.write_text("", encoding="utf-8")
    return {
        "id": run_id,
        "action_id": spec.id,
        "label": spec.label,
        "status": "denied",
        "error_code": "TOOL_POLICY_DENIED",
        "error_message": error_message,
        "exit_code": None,
        "duration_ms": 0,
        "argv": list(spec.argv),
        "cwd": str(spec.cwd),
        "writes": spec.writes,
        "remote": spec.remote,
        "stdout_path": str(stdout_path),
        "stderr_path": str(stderr_path),
        "metadata_path": str(metadata_path),
        "stdout_bytes": 0,
        "stderr_bytes": len(error_message.encode("utf-8")),
        "stdout_preview": "",
        "stderr_preview": error_message[:PREVIEW_CHARS],
        "stdout_preview_truncated": False,
        "stderr_preview_truncated": len(error_message) > PREVIEW_CHARS,
    }


def _minimal_env() -> dict[str, str]:
    return {
        "HOME": str(Path.home()),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "LC_ALL": os.environ.get("LC_ALL", "C.UTF-8"),
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "TZ": os.environ.get("TZ", "America/New_York"),
    }


def _preview(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")[:PREVIEW_CHARS]


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
    if not token:
        return False
    return (
        token.startswith("/")
        or token.startswith("~/")
        or token.startswith("./")
        or token.startswith("../")
        or "/" in token
    )


def _inside(path: Path, root: Path) -> bool:
    resolved = path.expanduser().resolve(strict=False)
    root_resolved = root.expanduser().resolve(strict=False)
    return resolved == root_resolved or root_resolved in resolved.parents


def _inside_any(path: Path, roots: tuple[Path, ...]) -> bool:
    return any(_inside(path, root) for root in roots)
