from delamain_backend.agent.tool_normalize import normalize_tool_calls


def test_normalizes_chat_completion_tool_calls():
    raw = {
        "choices": [
            {
                "message": {
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "function": {
                                "name": "get_now",
                                "arguments": "{\"ok\": true}",
                            },
                        }
                    ]
                }
            }
        ]
    }
    calls = normalize_tool_calls(raw, "chat_completions")
    assert calls[0].id == "call_1"
    assert calls[0].name == "get_now"
    assert calls[0].arguments == {"ok": True}
    assert calls[0].source_api_family == "chat_completions"


def test_normalizes_responses_function_calls():
    raw = {
        "output": [
            {
                "type": "function_call",
                "call_id": "call_2",
                "name": "delamain_ref",
                "arguments": "{\"status\": true}",
            }
        ]
    }
    calls = normalize_tool_calls(raw, "responses")
    assert calls[0].id == "call_2"
    assert calls[0].name == "delamain_ref"
    assert calls[0].arguments == {"status": True}
    assert calls[0].source_api_family == "responses"
