from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class NormalizedToolCall:
    id: str
    name: str
    arguments: dict[str, Any]
    source_api_family: str
    raw: Any


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _parse_arguments(value: Any) -> dict[str, Any]:
    if value is None or value == "":
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        parsed = json.loads(value)
        if not isinstance(parsed, dict):
            raise ValueError("Tool call arguments must decode to an object")
        return parsed
    raise ValueError("Unsupported tool call argument type")


def normalize_tool_calls(raw: Any, api_family: str) -> list[NormalizedToolCall]:
    if api_family == "chat_completions":
        return _normalize_chat_completions(raw)
    if api_family == "responses":
        return _normalize_responses(raw)
    raise ValueError(f"Unsupported api_family: {api_family}")


def _normalize_chat_completions(raw: Any) -> list[NormalizedToolCall]:
    choices = _get(raw, "choices", [])
    if not choices:
        return []
    message = _get(_get(choices[0], "message", {}), "message", _get(choices[0], "message", {}))
    calls = _get(message, "tool_calls", []) or []
    normalized: list[NormalizedToolCall] = []
    for call in calls:
        function = _get(call, "function", {})
        normalized.append(
            NormalizedToolCall(
                id=str(_get(call, "id", f"toolcall_{uuid.uuid4().hex}")),
                name=str(_get(function, "name")),
                arguments=_parse_arguments(_get(function, "arguments", "{}")),
                source_api_family="chat_completions",
                raw=call,
            )
        )
    return normalized


def _normalize_responses(raw: Any) -> list[NormalizedToolCall]:
    output = _get(raw, "output", []) or []
    normalized: list[NormalizedToolCall] = []
    for item in output:
        if _get(item, "type") != "function_call":
            continue
        normalized.append(
            NormalizedToolCall(
                id=str(_get(item, "call_id", _get(item, "id", f"toolcall_{uuid.uuid4().hex}"))),
                name=str(_get(item, "name")),
                arguments=_parse_arguments(_get(item, "arguments", "{}")),
                source_api_family="responses",
                raw=item,
            )
        )
    return normalized
