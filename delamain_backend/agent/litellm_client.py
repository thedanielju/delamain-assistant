from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import io
import json
import multiprocessing
import queue as queue_module
import uuid
from pathlib import Path
from typing import Any, Protocol

from delamain_backend.agent.router import api_family_for_route
from delamain_backend.agent.tool_normalize import normalize_tool_calls

_SAFE_RESPONSE_HEADER_MARKERS = (
    "copilot",
    "premium",
    "ratelimit",
    "rate-limit",
    "request",
    "usage",
)
_SENSITIVE_RESPONSE_HEADER_MARKERS = (
    "authorization",
    "api-key",
    "cookie",
    "secret",
    "token",
)
_NATIVE_FILE_PROVIDERS = (
    "anthropic",
    "bedrock",
    "gemini",
    "github_copilot",
    "google",
    "openai",
    "vertex_ai",
)
_NATIVE_FILE_MODEL_MARKERS = (
    "claude",
    "gemini",
    "gpt-4o",
    "gpt-5",
)
_TEXT_FILE_EXTENSIONS = {".md", ".txt"}


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
        prompt = _content_to_text(messages[-1].get("content")) if messages else ""
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
        formatted_messages = format_messages_for_api_family(messages, api_family, model_route)
        try:
            raw = await _run_litellm_in_child_process(
                model_route=model_route,
                api_family=api_family,
                messages=formatted_messages,
                tools=tools or [],
                timeout_seconds=self.timeout_seconds,
            )
        except ModelCallError as exc:
            if not _should_retry_with_file_text_fallback(exc, messages):
                raise
            fallback_messages = format_messages_for_api_family(
                messages,
                api_family,
                model_route,
                force_file_text_fallback=True,
            )
            raw = await _run_litellm_in_child_process(
                model_route=model_route,
                api_family=api_family,
                messages=fallback_messages,
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
    return _read_litellm_process_result(queue, model_route)


def _read_litellm_process_result(queue: Any, model_route: str) -> Any:
    try:
        status, payload = queue.get(timeout=5)
    except queue_module.Empty as exc:
        raise ModelCallError(
            f"Model route exited before response payload was available: {model_route}"
        ) from exc
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
    provider_usage = _to_plain_data(_get(data, "usage"))
    response_headers = _extract_response_headers(data)
    hidden_params = _extract_hidden_params(data)
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
        "usage": _normalize_usage(
            provider_usage,
            model_route,
            response_headers=response_headers,
            hidden_params=hidden_params,
        ),
        "provider_usage": provider_usage if isinstance(provider_usage, dict) else None,
        "response_headers": response_headers or None,
        "raw": data,
    }


def format_messages_for_api_family(
    messages: list[dict[str, Any]],
    api_family: str,
    model_route: str | None = None,
    *,
    force_file_text_fallback: bool = False,
) -> list[dict[str, Any]]:
    if api_family == "responses":
        formatted: list[dict[str, Any]] = []
        for message in messages:
            response_message = _format_response_message(
                message,
                model_route or "",
                force_file_text_fallback=force_file_text_fallback,
            )
            if isinstance(response_message, list):
                formatted.extend(response_message)
            else:
                formatted.append(response_message)
        return formatted
    return [
        _format_chat_message(
            message,
            model_route or "",
            force_file_text_fallback=force_file_text_fallback,
        )
        for message in messages
    ]


def _format_chat_message(
    message: dict[str, Any],
    model_route: str = "",
    *,
    force_file_text_fallback: bool = False,
) -> dict[str, Any]:
    role = message.get("role")
    if role == "assistant" and message.get("tool_calls"):
        return {
            "role": "assistant",
            "content": _format_chat_content(
                message.get("content"),
                model_route,
                force_file_text_fallback=force_file_text_fallback,
            )
            or None,
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
        "content": _format_chat_content(
            message.get("content"),
            model_route,
            force_file_text_fallback=force_file_text_fallback,
        ),
    }


def _format_response_message(
    message: dict[str, Any],
    model_route: str = "",
    *,
    force_file_text_fallback: bool = False,
) -> dict[str, Any] | list[dict[str, Any]]:
    role = message.get("role")
    if role == "assistant" and message.get("tool_calls"):
        formatted: list[dict[str, Any]] = []
        content = _content_to_text(message.get("content"))
        if content:
            formatted.append({"role": "assistant", "content": content})
        formatted.extend(
            {
                "type": "function_call",
                "call_id": call["id"],
                "name": call["name"],
                "arguments": json.dumps(call.get("arguments") or {}, sort_keys=True),
            }
            for call in message["tool_calls"]
        )
        return formatted
    if role == "tool":
        return {
            "type": "function_call_output",
            "call_id": message["tool_call_id"],
            "output": str(message.get("content") or ""),
        }
    return {
        "role": str(role),
        "content": _format_response_content(
            message.get("content"),
            model_route,
            force_file_text_fallback=force_file_text_fallback,
        ),
    }


def _format_chat_content(
    content: Any,
    model_route: str,
    *,
    force_file_text_fallback: bool = False,
) -> Any:
    if not isinstance(content, list):
        return str(content or "")
    parts = [
        _format_content_part(
            part,
            api_family="chat_completions",
            model_route=model_route,
            force_file_text_fallback=force_file_text_fallback,
        )
        for part in content
    ]
    text_parts = [part["text"] for part in parts if isinstance(part, dict) and part.get("type") == "text"]
    has_file = any(isinstance(part, dict) and part.get("type") == "file" for part in parts)
    if not has_file:
        return "\n\n".join(text for text in text_parts if text)
    return [part for part in parts if part]


def _format_response_content(
    content: Any,
    model_route: str,
    *,
    force_file_text_fallback: bool = False,
) -> Any:
    if not isinstance(content, list):
        return str(content or "")
    parts = [
        _format_content_part(
            part,
            api_family="responses",
            model_route=model_route,
            force_file_text_fallback=force_file_text_fallback,
        )
        for part in content
    ]
    text_parts = [
        part["text"]
        for part in parts
        if isinstance(part, dict) and part.get("type") in {"input_text", "text"}
    ]
    has_file = any(
        isinstance(part, dict) and part.get("type") in {"input_file", "file"}
        for part in parts
    )
    if not has_file:
        return "\n\n".join(text for text in text_parts if text)
    return [part for part in parts if part]


def _format_content_part(
    part: Any,
    *,
    api_family: str,
    model_route: str,
    force_file_text_fallback: bool = False,
) -> dict[str, Any]:
    if not isinstance(part, dict):
        return _text_part(str(part), api_family)
    part_type = str(part.get("type") or "")
    if part_type == "delamain_upload_file":
        return _format_delamain_file_part(
            part.get("file") or {},
            api_family,
            model_route,
            force_file_text_fallback=force_file_text_fallback,
        )
    if part_type == "text":
        return _text_part(str(part.get("text") or ""), api_family)
    return part


def _format_delamain_file_part(
    file_info: Any,
    api_family: str,
    model_route: str,
    *,
    force_file_text_fallback: bool = False,
) -> dict[str, Any]:
    if not isinstance(file_info, dict):
        return _text_part("", api_family)
    fallback_text = str(file_info.get("fallback_text") or "")
    filename = str(file_info.get("filename") or "upload")
    if force_file_text_fallback or not _route_supports_native_file(model_route, file_info):
        return _fallback_file_text_part(filename, fallback_text, api_family)
    data_url = _file_data_url(file_info)
    if not data_url:
        return _fallback_file_text_part(filename, fallback_text, api_family)
    mime_type = str(file_info.get("mime_type") or "application/octet-stream")
    if api_family == "responses":
        return {
            "type": "input_file",
            "filename": filename,
            "file_data": data_url,
        }
    return {
        "type": "file",
        "file": {
            "filename": filename,
            "file_data": data_url,
            "format": mime_type,
        },
    }


def _route_supports_native_file(model_route: str, file_info: dict[str, Any]) -> bool:
    filename = str(file_info.get("filename") or "")
    extension = Path(filename).suffix.lower()
    if extension in _TEXT_FILE_EXTENSIONS:
        return False
    route = str(model_route or "").lower()
    provider = route.split("/", 1)[0]
    if provider in _NATIVE_FILE_PROVIDERS:
        return True
    if provider == "openrouter":
        return any(marker in route for marker in _NATIVE_FILE_MODEL_MARKERS)
    return False


def _file_data_url(file_info: dict[str, Any]) -> str | None:
    path = Path(str(file_info.get("path") or ""))
    if not path.is_file():
        return None
    data = path.read_bytes()
    expected_sha = str(file_info.get("sha256") or "")
    if expected_sha and hashlib.sha256(data).hexdigest() != expected_sha:
        return None
    mime_type = str(file_info.get("mime_type") or "application/octet-stream")
    encoded = base64.b64encode(data).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def _fallback_file_text_part(filename: str, fallback_text: str, api_family: str) -> dict[str, Any]:
    if fallback_text:
        text = (
            f"Native file attachment was not available for {filename}; "
            "using extracted text fallback.\n\n"
            f"{fallback_text}"
        )
    else:
        text = f"Native file attachment was not available for {filename}."
    return _text_part(text, api_family)


def _text_part(text: str, api_family: str) -> dict[str, str]:
    if api_family == "responses":
        return {"type": "input_text", "text": text}
    return {"type": "text", "text": text}


def _content_to_text(content: Any) -> str:
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, dict):
                if part.get("type") == "text":
                    parts.append(str(part.get("text") or ""))
                elif part.get("type") == "delamain_upload_file":
                    file_info = part.get("file") or {}
                    if isinstance(file_info, dict):
                        parts.append(str(file_info.get("fallback_text") or ""))
            else:
                parts.append(str(part))
        return "\n\n".join(part for part in parts if part)
    return str(content or "")


def _should_retry_with_file_text_fallback(
    exc: ModelCallError,
    messages: list[dict[str, Any]],
) -> bool:
    if not _messages_have_native_file_parts(messages):
        return False
    lowered = str(exc).lower()
    markers = (
        "file",
        "pdf",
        "document",
        "input_file",
        "file_data",
        "unsupported",
        "invalid",
        "content type",
    )
    return any(marker in lowered for marker in markers)


def _messages_have_native_file_parts(messages: list[dict[str, Any]]) -> bool:
    for message in messages:
        content = message.get("content")
        if not isinstance(content, list):
            continue
        if any(
            isinstance(part, dict) and part.get("type") == "delamain_upload_file"
            for part in content
        ):
            return True
    return False


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


def _normalize_usage(
    usage: Any,
    model_route: str,
    *,
    response_headers: dict[str, Any] | None = None,
    hidden_params: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
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
    premium_units, premium_source = _premium_request_count(
        model_route, data, response_headers or {}
    )
    usage_source = "provider_body" if isinstance(data, dict) and data else "estimated"
    estimated = premium_source == "estimated_per_completed_call"
    return _usage_payload(
        model_route,
        input_tokens,
        output_tokens,
        premium_units=premium_units,
        estimated_cost_usd=_estimated_cost(data, hidden_params or {}),
        usage_source=usage_source,
        usage_estimated=estimated,
        premium_request_source=premium_source,
    )


def _usage_payload(
    model_route: str,
    input_tokens: int,
    output_tokens: int,
    *,
    premium_units: int | None = None,
    estimated_cost_usd: float | None = None,
    usage_source: str = "estimated",
    usage_estimated: bool = True,
    premium_request_source: str | None = None,
) -> dict[str, Any]:
    provider = model_route.split("/", 1)[0] if "/" in model_route else None
    return {
        "model": model_route,
        "provider": provider,
        "input_tokens": int(input_tokens or 0),
        "output_tokens": int(output_tokens or 0),
        "premium_units": premium_units,
        "estimated_cost_usd": estimated_cost_usd,
        "usage_source": usage_source,
        "usage_estimated": bool(usage_estimated),
        "premium_request_source": premium_request_source,
    }


def _premium_request_count(
    model_route: str, usage: Any, response_headers: dict[str, Any]
) -> tuple[int | None, str | None]:
    count = _first_int(
        usage,
        (
            "premium_request_count",
            "premium_requests",
            "premium_units",
            "billable_requests",
            "request_count",
        ),
    )
    if count is not None:
        return count, "provider_body"
    count = _first_int(
        response_headers,
        (
            "x-copilot-premium-request-count",
            "x-copilot-premium-requests",
            "x-copilot-premium-units",
            "x-premium-request-count",
            "x-premium-requests",
        ),
    )
    if count is not None:
        return count, "provider_headers"
    if model_route.startswith("github_copilot/"):
        return 1, "estimated_per_completed_call"
    return None, None


def _estimated_cost(usage: Any, hidden_params: dict[str, Any]) -> float | None:
    value = _first_number(
        usage,
        (
            "estimated_cost_usd",
            "cost_usd",
            "response_cost",
        ),
    )
    if value is not None:
        return value
    return _first_number(
        hidden_params,
        (
            "response_cost",
            "estimated_cost_usd",
            "cost_usd",
        ),
    )


def _first_int(value: Any, keys: tuple[str, ...]) -> int | None:
    number = _first_number(value, keys)
    return int(number) if number is not None else None


def _first_number(value: Any, keys: tuple[str, ...]) -> float | None:
    if not isinstance(value, dict):
        return None
    lowered = {str(key).lower(): item for key, item in value.items()}
    for key in keys:
        item = lowered.get(key.lower())
        if isinstance(item, bool):
            continue
        if isinstance(item, int | float):
            return float(item)
        if isinstance(item, str):
            try:
                return float(item)
            except ValueError:
                continue
    return None


def _extract_response_headers(data: Any) -> dict[str, Any]:
    headers = _find_dict(data, ("_response_headers", "response_headers"))
    if not headers:
        return {}
    return _safe_response_headers(headers)


def _extract_hidden_params(data: Any) -> dict[str, Any]:
    return _find_dict(data, ("_hidden_params", "hidden_params"))


def _find_dict(value: Any, keys: tuple[str, ...]) -> dict[str, Any]:
    if isinstance(value, dict):
        for key in keys:
            candidate = value.get(key)
            if isinstance(candidate, dict):
                return candidate
        for child in value.values():
            found = _find_dict(child, keys)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _find_dict(child, keys)
            if found:
                return found
    return {}


def _safe_response_headers(headers: dict[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, value in headers.items():
        name = str(key).lower()
        if any(marker in name for marker in _SENSITIVE_RESPONSE_HEADER_MARKERS):
            continue
        if not any(marker in name for marker in _SAFE_RESPONSE_HEADER_MARKERS):
            continue
        safe[name] = _to_plain_data(value)
    return safe


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
        dumped = _to_plain_data(model_dump())
        return _with_private_response_metadata(value, dumped)
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        dumped = _to_plain_data(to_dict())
        return _with_private_response_metadata(value, dumped)
    return str(value)


def _with_private_response_metadata(value: Any, dumped: Any) -> Any:
    if not isinstance(dumped, dict):
        return dumped
    for attr in ("_hidden_params", "_response_headers"):
        private_value = getattr(value, attr, None)
        if private_value:
            dumped[attr] = _to_plain_data(private_value)
    return dumped
