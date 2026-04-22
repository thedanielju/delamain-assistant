from dataclasses import replace

from delamain_backend.agent.tool_loop import MaxToolIterationsExceeded, check_tool_iteration
from delamain_backend.config import ToolsConfig
from delamain_backend.tools import default_tool_registry


def test_tool_registry_exposes_initial_m3_schemas(test_config):
    registry = default_tool_registry(test_config)
    names = {schema["function"]["name"] for schema in registry.schemas("chat_completions")}
    assert {"get_now", "delamain_ref", "delamain_vault_index", "get_health_status"} <= names
    response_names = {schema["name"] for schema in registry.schemas("responses")}
    assert names == response_names


def test_max_tool_iteration_guard(test_config):
    check_tool_iteration(7, test_config.tools.max_tool_iterations)
    try:
        check_tool_iteration(8, test_config.tools.max_tool_iterations)
    except MaxToolIterationsExceeded:
        return
    raise AssertionError("expected MaxToolIterationsExceeded")


async def test_tool_output_cap_marks_truncation(test_config):
    small_output_config = replace(
        test_config,
        tools=ToolsConfig(
            max_tool_iterations=8,
            default_timeout_seconds=2,
            output_limit_bytes=4,
        ),
    )
    registry = default_tool_registry(small_output_config)
    result = await registry.execute("get_now", {})
    assert result["truncated"] is True
    assert len(result["stdout"].encode()) <= 4


async def test_get_health_status_reports_helper_and_path_status(test_config):
    registry = default_tool_registry(test_config)
    result = await registry.execute("get_health_status", {})
    assert result["status"] == "success"
    import json

    payload = json.loads(result["stdout"])
    assert payload["helpers"]["now"]["ok"] is True
    assert payload["helpers"]["delamain_ref"]["ok"] is True
    assert payload["helpers"]["delamain_vault_index"]["ok"] is True
    assert payload["paths"]["llm_workspace"]["exists"] is True
