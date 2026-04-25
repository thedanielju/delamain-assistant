from delamain_backend.agent.router import api_family_for_route, fallback_chain


def test_gpt_54_mini_uses_responses():
    assert api_family_for_route("github_copilot/gpt-5.4-mini") == "responses"


def test_other_routes_use_chat_completions():
    assert api_family_for_route("github_copilot/gpt-5-mini") == "chat_completions"
    assert api_family_for_route("github_copilot/claude-haiku-4.5") == "chat_completions"


def test_gpt_54_mini_route_is_case_and_whitespace_insensitive():
    assert api_family_for_route(" github_copilot/gpt-5.4-mini ") == "responses"
    assert api_family_for_route("github_copilot/GPT-5.4-mini") == "responses"


def test_empty_route_is_rejected():
    try:
        api_family_for_route("")
    except ValueError as exc:
        assert str(exc) == "model_route is required"
        return
    raise AssertionError("expected ValueError for empty model route")


def test_fallback_chain_records_explicit_fallbacks():
    attempts = fallback_chain(
        requested_route="github_copilot/gpt-5.4-mini",
        high_volume_route="github_copilot/gpt-5-mini",
        cheap_route="github_copilot/claude-haiku-4.5",
        paid_route="openrouter/deepseek/deepseek-v3.2",
    )
    assert [attempt.model_route for attempt in attempts] == [
        "github_copilot/gpt-5.4-mini",
        "github_copilot/gpt-5-mini",
        "github_copilot/claude-haiku-4.5",
        "openrouter/deepseek/deepseek-v3.2",
    ]
    assert attempts[0].fallback_from is None
    assert attempts[1].fallback_from == "github_copilot/gpt-5.4-mini"
    assert attempts[1].fallback_reason == "previous_route_failed"
