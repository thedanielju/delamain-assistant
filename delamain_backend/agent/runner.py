from __future__ import annotations

import asyncio
import json
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any

from delamain_backend.agent.context import load_context_for_run
from delamain_backend.agent.litellm_client import LiteLLMModelClient, ModelClient, StubModelClient
from delamain_backend.agent.router import api_family_for_route, fallback_chain
from delamain_backend.agent.tool_loop import MaxToolIterationsExceeded
from delamain_backend.budget import copilot_budget_status, is_copilot_route
from delamain_backend.config import AppConfig
from delamain_backend.db import Database
from delamain_backend.errors import DelamainError, SensitiveLocked, ToolPolicyDenied
from delamain_backend.events import EventBus
from delamain_backend.settings_store import disabled_tools, tool_approval_policy
from delamain_backend.tools import ToolExecutionContext, ToolRegistry, default_tool_registry


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


class _RunCancelled(Exception):
    pass


class RunManager:
    def __init__(
        self,
        *,
        config: AppConfig,
        db: Database,
        bus: EventBus,
        model_client: ModelClient | None = None,
        tool_registry: ToolRegistry | None = None,
    ):
        self.config = config
        self.db = db
        self.bus = bus
        self.model_client = model_client or (
            LiteLLMModelClient(timeout_seconds=config.runtime.model_timeout_seconds)
            if config.runtime.enable_model_calls
            else StubModelClient()
        )
        self.tool_registry = tool_registry or default_tool_registry(config)
        self._tasks: set[asyncio.Task] = set()
        self._conversation_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    async def recover_on_startup(self) -> None:
        await self.db.execute(
            """
            UPDATE runs
            SET status = 'interrupted',
                error_code = 'RUN_INTERRUPTED',
                error_message = 'Backend restarted while run was in progress',
                completed_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            WHERE status = 'running'
            """
        )
        queued = await self.db.fetchall("SELECT id FROM runs WHERE status = 'queued'")
        for row in queued:
            self.enqueue(row["id"])

    def enqueue(self, run_id: str) -> None:
        task = asyncio.create_task(self.process_run(run_id))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def process_run(self, run_id: str) -> None:
        run = await self.db.fetchone("SELECT * FROM runs WHERE id = ?", (run_id,))
        if run is None:
            return
        conversation_id = run["conversation_id"]
        async with self._conversation_locks[conversation_id]:
            latest = await self.db.fetchone("SELECT * FROM runs WHERE id = ?", (run_id,))
            if latest is None or latest["status"] != "queued":
                return
            await self._run_body(latest)

    async def _run_body(self, run: dict[str, Any]) -> None:
        run_id = run["id"]
        conversation_id = run["conversation_id"]
        assistant_message_id = new_id("msg")
        try:
            await self.db.execute(
                """
                INSERT INTO messages(id, conversation_id, run_id, role, content, status)
                VALUES (?, ?, ?, 'assistant', '', 'streaming')
                """,
                (assistant_message_id, conversation_id, run_id),
            )
            await self.db.execute(
                """
                UPDATE runs
                SET status = 'running',
                    assistant_message_id = ?,
                    started_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                WHERE id = ?
                """,
                (assistant_message_id, run_id),
            )
            await self.bus.emit(
                conversation_id=conversation_id,
                run_id=run_id,
                event_type="run.started",
                payload={"run_id": run_id, "model_route": run["model_route"]},
            )

            loaded_context = load_context_for_run(self.config, run["context_mode"])
            if loaded_context.clock_refresh:
                await self.bus.emit(
                    conversation_id=conversation_id,
                    run_id=run_id,
                    event_type="audit",
                    payload={
                        "action": "context.clock_refreshed",
                        "summary": "Refreshed system-context clock block for this run",
                        **loaded_context.clock_refresh,
                    },
                )
            await self._persist_context_loads(run_id, loaded_context.items)
            await self.bus.emit(
                conversation_id=conversation_id,
                run_id=run_id,
                event_type="context.loaded",
                payload={"items": loaded_context.items},
            )

            messages = await self._initial_model_messages(
                run,
                context_messages=loaded_context.prompt_messages,
            )
            assistant_text = await self._run_model_tool_loop(
                run=run,
                assistant_message_id=assistant_message_id,
                messages=messages,
            )
            if await self._run_is_cancelled(run_id):
                await self._mark_assistant_message_cancelled(assistant_message_id)
                return

            await self.db.execute(
                """
                UPDATE messages
                SET content = ?, status = 'completed',
                    updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                WHERE id = ?
                """,
                (assistant_text, assistant_message_id),
            )
            await self.bus.emit(
                conversation_id=conversation_id,
                run_id=run_id,
                event_type="message.completed",
                payload={"message_id": assistant_message_id, "finish_reason": "stop"},
            )
            await self.db.execute(
                """
                UPDATE runs
                SET status = 'completed',
                    completed_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                WHERE id = ?
                """,
                (run_id,),
            )
            await self.bus.emit(
                conversation_id=conversation_id,
                run_id=run_id,
                event_type="run.completed",
                payload={"run_id": run_id, "status": "completed"},
            )
        except _RunCancelled:
            await self._mark_assistant_message_cancelled(assistant_message_id)
            return
        except Exception as exc:
            await self._fail_run(run, exc, assistant_message_id)

    async def _initial_model_messages(
        self,
        run: dict[str, Any],
        *,
        context_messages: list[dict[str, str]],
    ) -> list[dict[str, Any]]:
        user_message = await self.db.fetchone(
            "SELECT * FROM messages WHERE id = ?", (run["user_message_id"],)
        )
        return [
            {"role": "system", "content": "You are DELAMAIN."},
            *context_messages,
            {"role": "user", "content": user_message["content"] if user_message else ""},
        ]

    async def _run_model_tool_loop(
        self,
        *,
        run: dict[str, Any],
        assistant_message_id: str,
        messages: list[dict[str, Any]],
    ) -> str:
        text_parts: list[str] = []
        max_iterations = self.config.tools.max_tool_iterations
        for iteration in range(max_iterations + 1):
            if await self._run_is_cancelled(run["id"]):
                return "".join(text_parts) or "Cancelled."
            model_result = await self._call_model_with_fallback(run, messages)
            text = str(model_result.get("text") or "")
            if text:
                text_parts.append(text)
                await self._emit_text_delta(
                    conversation_id=run["conversation_id"],
                    run_id=run["id"],
                    message_id=assistant_message_id,
                    text=text,
                )

            tool_calls = model_result.get("tool_calls") or []
            if not tool_calls:
                return "".join(text_parts) or "Completed without assistant text."
            if iteration >= max_iterations:
                raise MaxToolIterationsExceeded(
                    f"Tool iteration limit reached: {max_iterations}"
                )

            messages.append({"role": "assistant", "content": text, "tool_calls": tool_calls})
            for call in tool_calls:
                if await self._run_is_cancelled(run["id"]):
                    return "".join(text_parts) or "Cancelled."
                tool_result_content = await self._execute_tool_call(
                    run,
                    call,
                    assistant_message_id=assistant_message_id,
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call["id"],
                        "name": call["name"],
                        "content": tool_result_content,
                    }
                )
        raise MaxToolIterationsExceeded(f"Tool iteration limit reached: {max_iterations}")

    async def _run_is_cancelled(self, run_id: str) -> bool:
        row = await self.db.fetchone("SELECT status FROM runs WHERE id = ?", (run_id,))
        return bool(row and row["status"] == "cancelled")

    async def _call_model_with_fallback(
        self,
        run: dict[str, Any],
        messages: list[dict[str, Any]],
    ) -> dict[str, Any]:
        attempts = fallback_chain(
            requested_route=run["model_route"],
            high_volume_route=self.config.models.fallback_high_volume,
            cheap_route=self.config.models.fallback_cheap,
            paid_route=self.config.models.paid_fallback,
        )
        if self.config.runtime.disable_model_fallbacks:
            attempts = attempts[:1]
        last_exc: Exception | None = None
        budget_warning_emitted = False
        for attempt in attempts:
            if is_copilot_route(attempt.model_route):
                budget = await copilot_budget_status(self.config, self.db)
                if budget["status"] in {"soft", "hard"} and not budget_warning_emitted:
                    action = (
                        "model.budget_override"
                        if budget["status"] == "hard" and budget["hard_override_enabled"]
                        else "model.budget_threshold"
                    )
                    await self.bus.emit(
                        conversation_id=run["conversation_id"],
                        run_id=run["id"],
                        event_type="audit",
                        payload={
                            "action": action,
                            "summary": (
                                "Copilot budget hard threshold overridden"
                                if action == "model.budget_override"
                                else f"Copilot budget threshold reached: {budget['status']}"
                            ),
                            "status": budget["status"],
                            "percent_used": budget["percent_used"],
                            "used_premium_requests": budget["used_premium_requests"],
                            "monthly_premium_requests": budget["monthly_premium_requests"],
                            "hard_override_enabled": budget["hard_override_enabled"],
                        },
                    )
                    budget_warning_emitted = True
                if budget["enforced"]:
                    model_call_id = new_id("modelcall")
                    await self.db.execute(
                        """
                        INSERT INTO model_calls(
                            id, run_id, model_route, api_family, status,
                            fallback_from, fallback_reason, error_message,
                            completed_at
                        )
                        VALUES (?, ?, ?, ?, 'blocked', ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                        """,
                        (
                            model_call_id,
                            run["id"],
                            attempt.model_route,
                            attempt.api_family,
                            attempt.fallback_from,
                            attempt.fallback_reason,
                            "Copilot budget hard threshold reached",
                        ),
                    )
                    last_exc = RuntimeError("Copilot budget hard threshold reached")
                    await self.bus.emit(
                        conversation_id=run["conversation_id"],
                        run_id=run["id"],
                        event_type="audit",
                        payload={
                            "action": "model.budget_blocked",
                            "summary": f"Blocked Copilot route over budget: {attempt.model_route}",
                            "model_route": attempt.model_route,
                            "status": budget["status"],
                            "percent_used": budget["percent_used"],
                            "used_premium_requests": budget["used_premium_requests"],
                            "monthly_premium_requests": budget["monthly_premium_requests"],
                        },
                    )
                    continue
            if attempt.fallback_from is not None:
                await self.bus.emit(
                    conversation_id=run["conversation_id"],
                    run_id=run["id"],
                    event_type="audit",
                    payload={
                        "action": "model.fallback",
                        "summary": f"Trying {attempt.model_route} after {attempt.fallback_from}",
                        "from": attempt.fallback_from,
                        "to": attempt.model_route,
                        "reason": attempt.fallback_reason,
                    },
                )
            model_call_id = new_id("modelcall")
            await self.db.execute(
                """
                INSERT INTO model_calls(
                    id, run_id, model_route, api_family, status,
                    fallback_from, fallback_reason
                )
                VALUES (?, ?, ?, ?, 'started', ?, ?)
                """,
                (
                    model_call_id,
                    run["id"],
                    attempt.model_route,
                    attempt.api_family,
                    attempt.fallback_from,
                    attempt.fallback_reason,
                ),
            )
            try:
                model_result = await self.model_client.complete(
                    model_route=attempt.model_route,
                    messages=messages,
                    tools=self.tool_registry.schemas(
                        attempt.api_family,
                        disabled_tools=await disabled_tools(self.db),
                    ),
                )
                actual_api_family = str(model_result.get('api_family') or '')
                if actual_api_family != attempt.api_family:
                    raise RuntimeError(
                        'Model route '
                        f'{attempt.model_route} returned unexpected api_family: '
                        f'expected {attempt.api_family}, got {actual_api_family or "unknown"}'
                    )
                actual_model = str(model_result.get("model") or attempt.model_route)
                if actual_model != attempt.model_route:
                    await self.bus.emit(
                        conversation_id=run["conversation_id"],
                        run_id=run["id"],
                        event_type="audit",
                        payload={
                            "action": "model.reported_route_mismatch",
                            "summary": (
                                f"Requested {attempt.model_route} but provider reported {actual_model}"
                            ),
                            "requested_model_route": attempt.model_route,
                            "reported_model": actual_model,
                            "api_family": attempt.api_family,
                        },
                    )
            except Exception as exc:
                last_exc = exc
                await self.db.execute(
                    """
                    UPDATE model_calls
                    SET status = 'failed',
                        error_message = ?,
                        completed_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                    WHERE id = ?
                    """,
                    (str(exc), model_call_id),
                )
                await self.bus.emit(
                    conversation_id=run["conversation_id"],
                    run_id=run["id"],
                    event_type="audit",
                    payload={
                        "action": "model.route_failed",
                        "summary": f"Model route failed: {attempt.model_route}",
                        "model_route": attempt.model_route,
                        "api_family": attempt.api_family,
                    },
                )
                continue

            usage = model_result.get("usage")
            await self.db.execute(
                """
                UPDATE model_calls
                SET status = 'completed',
                    usage_json = ?,
                    completed_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                WHERE id = ?
                """,
                (json.dumps(usage, sort_keys=True) if usage else None, model_call_id),
            )
            if usage:
                await self.bus.emit(
                    conversation_id=run["conversation_id"],
                    run_id=run["id"],
                    event_type="model.usage",
                    payload=_model_usage_event_payload(run["id"], attempt.model_route, usage),
                )
            return model_result

        raise RuntimeError(f"All model routes failed: {last_exc}")

    async def _execute_tool_call(
        self,
        run: dict[str, Any],
        call: dict[str, Any],
        *,
        assistant_message_id: str,
    ) -> str:
        tool_call_id = str(call["id"])
        tool_name = str(call["name"])
        arguments = call.get("arguments") or {}
        if not isinstance(arguments, dict):
            arguments = {}

        await self.bus.emit(
            conversation_id=run["conversation_id"],
            run_id=run["id"],
            event_type="tool.started",
            payload={
                "tool_call_id": tool_call_id,
                "assistant_message_id": assistant_message_id,
                "tool": tool_name,
                "name": tool_name,
                "arguments": arguments,
                "args": arguments,
                "summary": f"Run {tool_name}",
            },
        )
        await self.db.execute(
            """
            INSERT INTO tool_calls(id, run_id, tool, arguments, status)
            VALUES (?, ?, ?, ?, 'started')
            """,
            (tool_call_id, run["id"], tool_name, json.dumps(arguments, sort_keys=True)),
        )

        try:
            disabled = await disabled_tools(self.db)
            if tool_name in disabled:
                raise ToolPolicyDenied(f"Tool is disabled by settings: {tool_name}")
            approval_policy = await tool_approval_policy(
                self.db,
                tool_name,
                self.tool_registry.approval_policy_default(tool_name),
            )
            if approval_policy == "confirm":
                await self._await_tool_permission(
                    run=run,
                    tool_call_id=tool_call_id,
                    tool_name=tool_name,
                    arguments=arguments,
                )
            conversation = await self.db.fetchone(
                "SELECT sensitive_unlocked FROM conversations WHERE id = ?",
                (run["conversation_id"],),
            )
            result = await self.tool_registry.execute(
                tool_name,
                arguments,
                ToolExecutionContext(
                    conversation_id=run["conversation_id"],
                    run_id=run["id"],
                    sensitive_unlocked=bool(conversation and conversation["sensitive_unlocked"]),
                ),
            )
        except _RunCancelled as exc:
            await self.db.execute(
                """
                UPDATE tool_calls
                SET status = 'cancelled',
                    error_message = ?,
                    completed_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                WHERE id = ?
                """,
                (str(exc), tool_call_id),
            )
            await self.bus.emit(
                conversation_id=run["conversation_id"],
                run_id=run["id"],
                event_type="tool.finished",
                payload={
                    "tool_call_id": tool_call_id,
                    "assistant_message_id": assistant_message_id,
                    "status": "cancelled",
                    "duration_ms": 0,
                    "result_summary": str(exc)[:200],
                    "stdout": "",
                    "stderr": str(exc),
                },
            )
            raise
        except Exception as exc:
            if isinstance(exc, SensitiveLocked) or _arguments_target_sensitive(
                arguments, self.config.paths.sensitive
            ):
                await self._emit_sensitive_access_audit(
                    run=run,
                    tool_name=tool_name,
                    tool_call_id=tool_call_id,
                    status="denied",
                    reason=str(exc),
                )
            await self.db.execute(
                """
                UPDATE tool_calls
                SET status = 'failed',
                    error_message = ?,
                    completed_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                WHERE id = ?
                """,
                (str(exc), tool_call_id),
            )
            await self.bus.emit(
                conversation_id=run["conversation_id"],
                run_id=run["id"],
                event_type="tool.finished",
                payload={
                    "tool_call_id": tool_call_id,
                    "assistant_message_id": assistant_message_id,
                    "status": "failed",
                    "duration_ms": 0,
                    "result_summary": str(exc)[:200],
                    "stdout": "",
                    "stderr": str(exc),
                },
            )
            raise
        stdout = str(result.get("stdout") or "")
        stderr = str(result.get("stderr") or "")
        status = str(result.get("status") or "success")
        if result.get("root") == "sensitive":
            await self._emit_sensitive_access_audit(
                run=run,
                tool_name=tool_name,
                tool_call_id=tool_call_id,
                status="allowed",
            )

        if stdout:
            await self.bus.emit(
                conversation_id=run["conversation_id"],
                run_id=run["id"],
                event_type="tool.output",
                payload={
                    "tool_call_id": tool_call_id,
                    "assistant_message_id": assistant_message_id,
                    "stream": "stdout",
                    "text": stdout,
                    "chunk": stdout,
                },
            )
        if stderr:
            await self.bus.emit(
                conversation_id=run["conversation_id"],
                run_id=run["id"],
                event_type="tool.output",
                payload={
                    "tool_call_id": tool_call_id,
                    "assistant_message_id": assistant_message_id,
                    "stream": "stderr",
                    "text": stderr,
                    "chunk": stderr,
                },
            )
        if result.get("truncated"):
            await self.bus.emit(
                conversation_id=run["conversation_id"],
                run_id=run["id"],
                event_type="error",
                payload={
                    "code": "TOOL_OUTPUT_TRUNCATED",
                    "message": f"Tool output truncated for {tool_name}",
                    "details": {"tool_call_id": tool_call_id},
                },
            )

        await self.db.execute(
            """
            UPDATE tool_calls
            SET status = ?, stdout = ?, stderr = ?, result_json = ?,
                completed_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            WHERE id = ?
            """,
            (
                status,
                stdout or None,
                stderr or None,
                json.dumps(result, sort_keys=True),
                tool_call_id,
            ),
        )
        await self.bus.emit(
            conversation_id=run["conversation_id"],
            run_id=run["id"],
            event_type="tool.finished",
            payload={
                "tool_call_id": tool_call_id,
                "assistant_message_id": assistant_message_id,
                "status": status,
                "duration_ms": int(result.get("duration_ms") or 0),
                "result_summary": _summarize_tool_result(result),
                "stdout": stdout,
                "stderr": stderr,
            },
        )

        content = json.dumps(result, sort_keys=True)
        await self.db.execute(
            """
            INSERT INTO messages(id, conversation_id, run_id, role, content, status)
            VALUES (?, ?, ?, 'tool', ?, ?)
            """,
            (new_id("msg"), run["conversation_id"], run["id"], content, status),
        )
        return content

    async def _await_tool_permission(
        self,
        *,
        run: dict[str, Any],
        tool_call_id: str,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> None:
        permission_id = new_id("perm")
        details = {
            "tool_call_id": tool_call_id,
            "tool": tool_name,
            "arguments": arguments,
            "approval_policy": "confirm",
        }
        await self.db.execute(
            """
            INSERT INTO permissions(
                id, conversation_id, run_id, kind, summary, details_json
            )
            VALUES (?, ?, ?, 'tool', ?, ?)
            """,
            (
                permission_id,
                run["conversation_id"],
                run["id"],
                f"Approve tool call: {tool_name}",
                json.dumps(details, sort_keys=True),
            ),
        )
        await self.db.execute(
            """
            UPDATE runs
            SET status = 'waiting_approval'
            WHERE id = ?
            """,
            (run["id"],),
        )
        await self.bus.emit(
            conversation_id=run["conversation_id"],
            run_id=run["id"],
            event_type="permission.requested",
            payload={
                "run_id": run["id"],
                "permission_id": permission_id,
                "kind": "tool",
                "summary": f"Approve tool call: {tool_name}",
                "details": details,
            },
        )
        while True:
            if await self._run_is_cancelled(run["id"]):
                await self._resolve_permission(
                    permission_id=permission_id,
                    conversation_id=run["conversation_id"],
                    run_id=run["id"],
                    decision="denied",
                    resolver="system",
                    note="Run cancelled while awaiting approval",
                )
                raise _RunCancelled(
                    f"Run cancelled while awaiting approval for tool call: {tool_name}"
                )
            row = await self.db.fetchone(
                "SELECT status, decision FROM permissions WHERE id = ?",
                (permission_id,),
            )
            if row and row["status"] == "resolved":
                if row["decision"] == "approved":
                    if await self._run_is_cancelled(run["id"]):
                        raise _RunCancelled(
                            f"Run cancelled while awaiting approval for tool call: {tool_name}"
                        )
                    await self.db.execute(
                        "UPDATE runs SET status = 'running' WHERE id = ?",
                        (run["id"],),
                    )
                    return
                raise ToolPolicyDenied(f"Permission denied for tool call: {tool_name}")
            await asyncio.sleep(0.25)

    async def _resolve_permission(
        self,
        *,
        permission_id: str,
        conversation_id: str,
        run_id: str,
        decision: str,
        resolver: str,
        note: str | None = None,
    ) -> None:
        row = await self.db.fetchone("SELECT * FROM permissions WHERE id = ?", (permission_id,))
        if row is None or row["status"] != "pending":
            return
        await self.db.execute(
            """
            UPDATE permissions
            SET status = 'resolved',
                decision = ?,
                note = ?,
                resolver = ?,
                resolved_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            WHERE id = ?
            """,
            (decision, note, resolver, permission_id),
        )
        await self.bus.emit(
            conversation_id=conversation_id,
            run_id=run_id,
            event_type="permission.resolved",
            payload={
                "run_id": run_id,
                "permission_id": permission_id,
                "decision": decision,
                "resolver": resolver,
                "note": note,
            },
        )

    async def _emit_sensitive_access_audit(
        self,
        *,
        run: dict[str, Any],
        tool_name: str,
        tool_call_id: str,
        status: str,
        reason: str | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "action": "sensitive.access",
            "summary": f"Sensitive access {status}: {tool_name}",
            "tool": tool_name,
            "tool_call_id": tool_call_id,
            "status": status,
        }
        if reason:
            payload["reason"] = reason[:500]
        await self.bus.emit(
            conversation_id=run["conversation_id"],
            run_id=run["id"],
            event_type="audit",
            payload=payload,
        )

    async def _emit_text_delta(
        self,
        *,
        conversation_id: str,
        run_id: str,
        message_id: str,
        text: str,
    ) -> None:
        for chunk in _chunks(text, 96):
            await self.bus.emit(
                conversation_id=conversation_id,
                run_id=run_id,
                event_type="message.delta",
                payload={"message_id": message_id, "text": chunk},
            )
            await asyncio.sleep(0)

    async def _mark_assistant_message_cancelled(self, assistant_message_id: str) -> None:
        await self.db.execute(
            """
            UPDATE messages
            SET status = 'cancelled',
                updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            WHERE id = ?
            """,
            (assistant_message_id,),
        )

    async def _persist_context_loads(self, run_id: str, items: list[dict]) -> None:
        for item in items:
            await self.db.execute(
                """
                INSERT INTO context_loads(id, run_id, path, mode, byte_count, sha256, included)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    new_id("ctx"),
                    run_id,
                    item["path"],
                    item["mode"],
                    item["byte_count"],
                    item["sha256"],
                    1 if item["included"] else 0,
                ),
            )

    async def _fail_run(
        self, run: dict[str, Any], exc: Exception, assistant_message_id: str | None
    ) -> None:
        code = exc.code if isinstance(exc, DelamainError) else "RUN_FAILED"
        message = str(exc)
        await self.db.execute(
            """
            UPDATE runs
            SET status = 'failed',
                error_code = ?,
                error_message = ?,
                completed_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            WHERE id = ?
            """,
            (code, message, run["id"]),
        )
        if assistant_message_id:
            await self.db.execute(
                "UPDATE messages SET status = 'failed', updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?",
                (assistant_message_id,),
            )
        await self.bus.emit(
            conversation_id=run["conversation_id"],
            run_id=run["id"],
            event_type="error",
            payload={"code": code, "message": message, "details": None},
        )
        await self.bus.emit(
            conversation_id=run["conversation_id"],
            run_id=run["id"],
            event_type="run.completed",
            payload={"run_id": run["id"], "status": "failed"},
        )


def _chunks(text: str, size: int) -> list[str]:
    return [text[index : index + size] for index in range(0, len(text), size)] or [""]


def _summarize_tool_result(result: dict[str, Any]) -> str:
    stdout = str(result.get("stdout") or "").strip()
    stderr = str(result.get("stderr") or "").strip()
    if stdout:
        return stdout[:200]
    if stderr:
        return stderr[:200]
    return str(result.get("status") or "completed")


def _model_usage_event_payload(
    run_id: str,
    model_route: str,
    usage: dict[str, Any],
) -> dict[str, Any]:
    input_tokens = usage.get("input_tokens")
    output_tokens = usage.get("output_tokens")
    return {
        **usage,
        "run_id": run_id,
        "model_route": model_route,
        "prompt_tokens": input_tokens,
        "completion_tokens": output_tokens,
        "premium_request_count": usage.get("premium_units"),
        "estimated_cost": usage.get("estimated_cost_usd"),
    }


def _arguments_target_sensitive(arguments: dict[str, Any], sensitive_root: Path) -> bool:
    raw_path = arguments.get("path")
    if not isinstance(raw_path, str):
        return False
    try:
        candidate = Path(raw_path).expanduser()
        if not candidate.is_absolute():
            return False
        resolved = candidate.resolve(strict=False)
        root = sensitive_root.expanduser().resolve(strict=False)
    except OSError:
        return False
    return resolved == root or root in resolved.parents
