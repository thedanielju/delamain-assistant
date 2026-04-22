from __future__ import annotations

from dataclasses import dataclass

RESPONSES_ONLY_ROUTE = "github_copilot/gpt-5.4-mini"


def api_family_for_route(model_route: str) -> str:
    normalized_route = str(model_route or "").strip().lower()
    if normalized_route == RESPONSES_ONLY_ROUTE:
        return "responses"
    return "chat_completions"


@dataclass(frozen=True)
class FallbackAttempt:
    model_route: str
    api_family: str
    fallback_from: str | None
    fallback_reason: str | None


def fallback_chain(
    *,
    requested_route: str,
    high_volume_route: str,
    cheap_route: str,
    paid_route: str,
) -> list[FallbackAttempt]:
    ordered = [requested_route, high_volume_route, cheap_route, paid_route]
    deduped: list[str] = []
    for route in ordered:
        if route and route not in deduped:
            deduped.append(route)
    attempts: list[FallbackAttempt] = []
    previous: str | None = None
    for index, route in enumerate(deduped):
        attempts.append(
            FallbackAttempt(
                model_route=route,
                api_family=api_family_for_route(route),
                fallback_from=previous,
                fallback_reason=None if index == 0 else "previous_route_failed",
            )
        )
        previous = route
    return attempts
