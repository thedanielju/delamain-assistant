from __future__ import annotations

import asyncio
import contextlib
import io
import json
import multiprocessing
import uuid
from typing import Any, Protocol

from delamain_backend.agent.router import api_family_for_route
from delamain_backend.agent.tool_normalize import normalize_tool_calls


class ModelCallError(RuntimeError):
    pass


class ModelClient(Protocol):
    async def complete(
        self,
        *,
        model_route: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        ...


class StubModelClient:
    async def complete(
        self,
        *,
        model_route: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        prompt = messages[-1]["content"] if messages else ""
        if _should_stub_tool_call(prompt, messages):
            return {
                "id": f"stub_{uuid.uuid4().hex}",
                "model": model_route,
                "api_family": api_family_for_route(model_route),
                "text": "",
                "tool_calls": [_stub_tool_call(prompt)],
                "usage": _usage_payload(model_route, 0, 0),
                "raw": None,
            }
        tool_result = _latest_tool_result(messages)
        if tool_result is not None:
            text = f"Tool result: {tool_result[:500]}"
        else:
            text = f"DELAMAIN backend stub response: {prompt[:500]}"
        return {
            "id": f"stub_{uuid.uuid4().hex}",
            "model": model_route,
            "api_family": api_family_for_route(model_route),
            "text": text,
            "tool_calls": [],
            "usage": _usage_payload(model_route, len(prompt.split()), len(text.split())),
            "raw": None,
        }


class LiteLLMModelClient:
    def __init__(self, timeout_seconds: int = 30):
        self.timeout_seconds = timeout_seconds

    async def complete(
        self,
        *,
        model_route: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        api_family = api_family_for_route(model_route)
        formatted_messages = format_messages_for_api_family(messages, api_family)
        raw = await _run_litellm_in_child_process(
            model_route=model_route,
            api_family=api_family,
            messages=formatted_messages,
            tools=tools or [],
            timeout_seconds=self.timeout_seconds,
        )
        return normalize_model_result(raw, model_route=model_route, api_family=api_family)


async def _run_litellm_in_child_process(
    *,
    model_route: str,
    api_family: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    timeout_seconds: int,
) -> Any:
    return await asyncio.to_thread(
        _run_litellm_process_sync,
        model_route,
        api_family,
        messages,
        tools,
        timeout_seconds,
    )


def _run_litellm_process_sync(
    model_route: str,
    api_family: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    timeout_seconds: int,
) -> Any:
    ctx = multiprocessing.get_context("spawn")
    queue = ctx.Queue(maxsize=1)
    process = ctx.Process(
        target=_litellm_worker,
        args=(queue, model_route, api_family, messages, tools, timeout_seconds),
    )
    process.start()
    process.join(timeout_seconds + 5)
    if process.is_alive():
        process.terminate()
        process.join(5)
        raise ModelCallError(f"Model route timed out after {timeout_seconds}s: {model_route}")
    if queue.empty():
        raise ModelCallError(f"Model route exited without a response: {model_route}")
    status, payload = queue.get()
    if status == "error":
        raise ModelCallError(str(payload))
    return payload


def _litellm_worker(
    queue: multiprocessing.Queue,
    model_route: str,
    api_family: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    timeout_seconds: int,
) -> None:
    try:
        captured_stdout = io.StringIO()
        captured_stderr = io.StringIO()
        with contextlib.redirect_stdout(captured_stdout), contextlib.redirect_stderr(
            captured_stderr
        ):
            import litellm

            if api_family == "responses":
                response = litellm.responses(
                    model=model_route,
                    input=messages,
                    tools=tools,
                    timeout=timeout_seconds,
                )
            else:
                response = litellm.completion(
                    model=model_route,
                    messages=messages,
                    tools=tools,
                    timeout=timeout_seconds,
                )
        queue.put(("ok", _to_plain_data(response)))
    except Exception as exc:
        queue.put(("error", f"{type(exc).__name__}: {exc}"))


def normalize_model_result(raw: Any, *, model_route: str, api_family: str) -> dict[str, Any]:
    data = _to_plain_data(raw)
    return {
        "id": str(_get(data, "id", f"model_{uuid.uuid4().hex}")),
        "model": str(_get(data, "model", model_route) or model_route),
        "api_family": api_family,
        "text": _extract_text(data, api_family),
        "tool_calls": [
            {
                "id": call.id,
                "name": call.name,
                "arguments": call.arguments,
                "source_api_family": call.source_api_family,
                "raw": _to_plain_data(call.raw),
            }
            for call in normalize_tool_calls(data, api_family)
        ],
        "usage": _normalize_usage(_get(data, "usage"), model_route),
        "raw": data,
    }


def format_messages_for_api_family(
    messages: list[dict[str, Any]], api_family: str
) -> list[dict[str, Any]]:
    if api_family == "responses":
        formatted: list[dict[str, Any]] = []
        for message in messages:
            response_message = _format_response_message(message)
            if isinstance(response_message, list):
                formatted.extend(response_message)
            else:
                formatted.append(response_message)
        return formatted
    return [_format_chat_message(message) for message in messages]


def _format_chat_message(message: dict[str, Any]) -> dict[str, Any]:
    role = message.get("role")
    if role == "assistant" and message.get("tool_calls"):
        return {
            "role": "assistant",
            "content": message.get("content") or None,
            "tool_calls": [
                {
                    "id": call["id"],
                    "type": "function",
                    "function": {
                        "name": call["name"],
                        "arguments": json.dumps(call.get("arguments") or {}, sort_keys=True),
                    },
                }
                for call in message["tool_calls"]
            ],
        }
    if role == "tool":
        return {
            "role": "tool",
            "tool_call_id": message["tool_call_id"],
            "content": str(message.get("content") or ""),
        }
    return {
        "role": str(role),
        "content": str(message.get("content") or ""),
    }


def _format_response_message(message: dict[str, Any]) -> dict[str, Any] | list[dict[str, Any]]:
    role = message.get("role")
    if role == "assistant" and message.get("tool_calls"):
        return [
            {
                "type": "function_call",
                "call_id": call["id"],
                "name": call["name"],
                "arguments": json.dumps(call.get("arguments") or {}, sort_keys=True),
            }
            for call in message["tool_calls"]
        ]
    if role == "tool":
        return {
            "type": "function_call_output",
            "call_id": message["tool_call_id"],
            "output": str(message.get("content") or ""),
        }
    return {
        "role": str(role),
        "content": str(message.get("content") or ""),
    }


def _extract_text(data: Any, api_family: str) -> str:
    if api_family == "chat_completions":
        choices = _get(data, "choices", []) or []
        if not choices:
            return ""
        message = _get(choices[0], "message", {}) or {}
        return str(_get(message, "content", "") or "")

    output_text = _get(data, "output_text")
    if output_text:
        return str(output_text)
    parts: list[str] = []
    for item in _get(data, "output", []) or []:
        if _get(item, "type") == "message":
            for content in _get(item, "content", []) or []:
                text = _get(content, "text")
                if text:
                    parts.append(str(text))
        elif _get(item, "type") in {"output_text", "text"}:
            text = _get(item, "text")
            if text:
                parts.append(str(text))
    return "".join(parts)


def _normalize_usage(usage: Any, model_route: str) -> dict[str, Any] | None:
    if usage is None:
        return None
    data = _to_plain_data(usage)
    input_tokens = (
        _get(data, "input_tokens")
        or _get(data, "prompt_tokens")
        or _get(data, "total_input_tokens")
        or 0
    )
    output_tokens = (
        _get(data, "output_tokens")
        or _get(data, "completion_tokens")
        or _get(data, "total_output_tokens")
        or 0
    )
    return _usage_payload(model_route, input_tokens, output_tokens)


def _usage_payload(model_route: str, input_tokens: int, output_tokens: int) -> dict[str, Any]:
    provider = model_route.split("/", 1)[0] if "/" in model_route else None
    return {
        "model": model_route,
        "provider": provider,
        "input_tokens": int(input_tokens or 0),
        "output_tokens": int(output_tokens or 0),
        "premium_units": None,
        "estimated_cost_usd": None,
    }


def _should_stub_tool_call(prompt: str, messages: list[dict[str, Any]]) -> bool:
    if any(message.get("role") == "tool" for message in messages):
        return False
    lowered = prompt.lower()
    return any(
        marker in lowered
        for marker in ["what time", "current time", "now", "vault index", "reference status"]
    )


def _stub_tool_call(prompt: str) -> dict[str, Any]:
    lowered = prompt.lower()
    if "vault index" in lowered:
        name = "delamain_vault_index"
    elif "reference status" in lowered:
        name = "delamain_ref"
    else:
        name = "get_now"
    return {
        "id": f"toolcall_{uuid.uuid4().hex}",
        "name": name,
        "arguments": {},
        "source_api_family": "stub",
        "raw": {},
    }


def _latest_tool_result(messages: list[dict[str, Any]]) -> str | None:
    for message in reversed(messages):
        if message.get("role") == "tool":
            content = message.get("content")
            if isinstance(content, str):
                return content
            return json.dumps(content, sort_keys=True)
    return None


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _to_plain_data(value: Any) -> Any:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, list):
        return [_to_plain_data(item) for item in value]
    if isinstance(value, tuple):
        return [_to_plain_data(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _to_plain_data(item) for key, item in value.items()}
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return _to_plain_data(model_dump())
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return _to_plain_data(to_dict())
    return str(value)
