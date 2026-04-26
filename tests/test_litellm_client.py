from delamain_backend.agent.litellm_client import (
    _read_litellm_process_result,
    format_messages_for_api_family,
    normalize_model_result,
)


def test_normalizes_chat_model_text_usage_and_tool_calls():
    raw = {
        "id": "chat_1",
        "model": "github_copilot/gpt-5-mini",
        "choices": [
            {
                "message": {
                    "content": "hello",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "function": {
                                "name": "get_now",
                                "arguments": "{}",
                            },
                        }
                    ],
                }
            }
        ],
        "usage": {"prompt_tokens": 3, "completion_tokens": 4},
    }
    result = normalize_model_result(
        raw,
        model_route="github_copilot/gpt-5-mini",
        api_family="chat_completions",
    )
    assert result["text"] == "hello"
    assert result["tool_calls"][0]["name"] == "get_now"
    assert result["usage"]["input_tokens"] == 3
    assert result["usage"]["output_tokens"] == 4


def test_normalizes_responses_model_text_usage_and_tool_calls():
    raw = {
        "id": "resp_1",
        "output": [
            {
                "type": "message",
                "content": [{"type": "output_text", "text": "done"}],
            },
            {
                "type": "function_call",
                "call_id": "call_2",
                "name": "delamain_ref",
                "arguments": "{}",
            },
        ],
        "usage": {"input_tokens": 5, "output_tokens": 6},
    }
    result = normalize_model_result(
        raw,
        model_route="github_copilot/gpt-5.4-mini",
        api_family="responses",
    )
    assert result["text"] == "done"
    assert result["tool_calls"][0]["source_api_family"] == "responses"
    assert result["usage"]["provider"] == "github_copilot"


def test_normalizes_copilot_authoritative_usage_metadata():
    raw = {
        "id": "chat_2",
        "model": "github_copilot/gpt-5-mini",
        "choices": [{"message": {"content": "hello"}}],
        "usage": {
            "prompt_tokens": 3,
            "completion_tokens": 4,
            "premium_request_count": 2,
        },
        "_response_headers": {
            "x-copilot-premium-requests": "2",
            "authorization": "Bearer should-not-persist",
        },
        "_hidden_params": {"response_cost": 0.0123},
    }
    result = normalize_model_result(
        raw,
        model_route="github_copilot/gpt-5-mini",
        api_family="chat_completions",
    )

    assert result["usage"]["premium_units"] == 2
    assert result["usage"]["premium_request_source"] == "provider_body"
    assert result["usage"]["usage_source"] == "provider_body"
    assert result["usage"]["usage_estimated"] is False
    assert result["usage"]["estimated_cost_usd"] == 0.0123
    assert result["provider_usage"]["premium_request_count"] == 2
    assert result["response_headers"] == {"x-copilot-premium-requests": "2"}


def test_normalizes_copilot_estimated_premium_request_when_provider_omits_count():
    raw = {
        "id": "chat_3",
        "model": "github_copilot/gpt-5-mini",
        "choices": [{"message": {"content": "hello"}}],
        "usage": {"prompt_tokens": 3, "completion_tokens": 4},
    }
    result = normalize_model_result(
        raw,
        model_route="github_copilot/gpt-5-mini",
        api_family="chat_completions",
    )

    assert result["usage"]["premium_units"] == 1
    assert result["usage"]["premium_request_source"] == "estimated_per_completed_call"
    assert result["usage"]["usage_estimated"] is True


def test_formats_tool_loop_messages_for_chat_completions():
    messages = [
        {"role": "user", "content": "time"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "call_1", "name": "get_now", "arguments": {}}],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": "noon"},
    ]
    formatted = format_messages_for_api_family(messages, "chat_completions")
    assert formatted[1]["tool_calls"][0]["function"]["name"] == "get_now"
    assert formatted[2] == {
        "role": "tool",
        "tool_call_id": "call_1",
        "content": "noon",
    }


def test_formats_tool_loop_messages_for_responses_api():
    messages = [
        {"role": "user", "content": "time"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "call_1", "name": "get_now", "arguments": {}}],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": "noon"},
    ]
    formatted = format_messages_for_api_family(messages, "responses")
    assert formatted[1] == {
        "type": "function_call",
        "call_id": "call_1",
        "name": "get_now",
        "arguments": "{}",
    }
    assert formatted[2] == {
        "type": "function_call_output",
        "call_id": "call_1",
        "output": "noon",
    }


def test_formats_responses_api_preserves_assistant_text_with_tool_call():
    messages = [
        {
            "role": "assistant",
            "content": "I will check that.",
            "tool_calls": [{"id": "call_1", "name": "get_now", "arguments": {}}],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": "noon"},
    ]

    formatted = format_messages_for_api_family(messages, "responses")

    assert formatted[0] == {"role": "assistant", "content": "I will check that."}
    assert formatted[1] == {
        "type": "function_call",
        "call_id": "call_1",
        "name": "get_now",
        "arguments": "{}",
    }
    assert formatted[2] == {
        "type": "function_call_output",
        "call_id": "call_1",
        "output": "noon",
    }


def test_reads_child_process_result_without_queue_empty_probe():
    class FakeQueue:
        def empty(self):
            raise AssertionError("empty should not be used for multiprocessing queues")

        def get(self, *, timeout):
            assert timeout == 5
            return ("ok", {"text": "done"})

    assert _read_litellm_process_result(FakeQueue(), "github_copilot/gpt-5-mini") == {
        "text": "done"
    }
