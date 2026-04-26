from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from delamain_backend.budget import copilot_budget_status
from delamain_backend.config import AppConfig
from delamain_backend.db import Database
from delamain_backend.subscription_status import subscription_status

PROVIDERS = ("copilot", "claude", "codex", "openrouter")


def _month_start_utc() -> str:
    now = datetime.now(UTC)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%S.%fZ"
    )


async def usage_summary(config: AppConfig, db: Database) -> dict[str, Any]:
    provider_counts = await _provider_counts(db)
    copilot = await copilot_budget_status(config, db)
    openrouter_credits = _openrouter_credits(config)
    anthropic_costs = _anthropic_costs(config)
    openai_costs = _openai_costs(config)
    subscriptions = subscription_status(config)
    claude_subscription = subscriptions["providers"]["claude"]
    codex_subscription = subscriptions["providers"]["codex"]
    providers = [
        {
            "provider": "copilot",
            "label": "GitHub Copilot",
            "period": copilot["period"],
            "unit": "premium_requests",
            "used": copilot["used_premium_requests"],
            "limit_or_credits": copilot["monthly_premium_requests"],
            "percent_used": copilot["percent_used"],
            "status": copilot["status"],
            "wired": True,
            "details": {
                "soft_threshold_percent": copilot["soft_threshold_percent"],
                "hard_threshold_percent": copilot["hard_threshold_percent"],
                "hard_override_enabled": copilot["hard_override_enabled"],
                "enforced": copilot["enforced"],
                "tracked_model_calls": copilot["tracked_model_calls"],
                "authoritative_premium_requests": copilot[
                    "authoritative_premium_requests"
                ],
                "estimated_premium_requests": copilot["estimated_premium_requests"],
                "usage_estimated": copilot["usage_estimated"],
                "usage_source": copilot["usage_source"],
                "last_observed_at": copilot["last_observed_at"],
                "reset": _copilot_reset_details(copilot["period"]),
            },
        },
        _stub_provider(
            "claude",
            "Claude",
            provider_counts.get("claude", 0),
            reason="ANTHROPIC_ADMIN_API_KEY is required for Anthropic Usage and Cost API.",
            billing=anthropic_costs,
            subscription=claude_subscription,
        ),
        _stub_provider(
            "codex",
            "Codex / OpenAI",
            provider_counts.get("codex", 0),
            reason=(
                "OPENAI_ADMIN_API_KEY or OPENAI_API_KEY is required for OpenAI organization "
                "cost reporting. Codex subscription billing has no public API hook here."
            ),
            billing=openai_costs,
            subscription=codex_subscription,
        ),
        {
            **_stub_provider(
                "openrouter",
                "OpenRouter",
                provider_counts.get("openrouter", 0),
                reason="OpenRouter call counts come from model_calls; credits require OPENROUTER_API_KEY.",
            ),
            "limit_or_credits": openrouter_credits.get("credits"),
            "status": openrouter_credits.get("status", "not_configured"),
            "wired": openrouter_credits.get("status") == "ok",
            "details": {
                "reason": openrouter_credits.get("reason"),
                "configured": openrouter_credits.get("configured"),
                "source": openrouter_credits.get("source"),
                "remaining_credits": openrouter_credits.get("remaining_credits"),
                "total_credits": openrouter_credits.get("credits"),
                "total_usage": openrouter_credits.get("total_usage"),
                "reset": _unknown_reset_details(),
            },
        },
    ]
    return {
        "period": "current_month_utc",
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "providers": providers,
        "subscriptions": subscriptions,
    }


async def _provider_counts(db: Database) -> dict[str, int]:
    rows = await db.fetchall(
        """
        SELECT model_route, COUNT(*) AS count
        FROM model_calls
        WHERE status = 'completed'
          AND created_at >= ?
        GROUP BY model_route
        """,
        (_month_start_utc(),),
    )
    counts = {provider: 0 for provider in PROVIDERS}
    for row in rows:
        provider = _provider_for_route(str(row["model_route"]))
        if provider in counts:
            counts[provider] += int(row["count"] or 0)
    return counts


def _provider_for_route(model_route: str) -> str:
    route = model_route.lower()
    if route.startswith("github_copilot/"):
        return "copilot"
    if route.startswith("openrouter/"):
        return "openrouter"
    if route.startswith(("anthropic/", "claude/")):
        return "claude"
    if route.startswith(("codex/", "openai/codex")) or "/codex" in route:
        return "codex"
    return route.split("/", 1)[0] if "/" in route else "unknown"


def _stub_provider(
    provider: str,
    label: str,
    used: int,
    *,
    reason: str,
    billing: dict[str, Any] | None = None,
    subscription: dict[str, Any] | None = None,
) -> dict[str, Any]:
    billing = billing or {"status": "not_configured", "reason": reason}
    status = billing.get("status", "not_configured")
    wired = status == "ok"
    if not wired and subscription and subscription.get("aggregate_status") == "ok":
        status = "auth_ok_billing_not_configured"
    return {
        "provider": provider,
        "label": label,
        "period": "current_month_utc",
        "unit": "usd" if billing.get("status") == "ok" else "calls",
        "used": used,
        "limit_or_credits": billing.get("amount_usd"),
        "percent_used": None,
        "status": status,
        "wired": wired,
        "details": {
            "reason": billing.get("reason"),
            "amount_usd": billing.get("amount_usd"),
            "currency": billing.get("currency"),
            "source": billing.get("source"),
            "subscription": subscription,
            "reset": _subscription_reset_details(subscription),
        },
    }


def _copilot_reset_details(period: str | None) -> dict[str, Any]:
    if period != "current_month_utc":
        return _unknown_reset_details()
    current_window_started_at = _month_start_datetime()
    next_reset_at = _next_month_start_datetime(current_window_started_at)
    return {
        "status": "known",
        "source": "current_month_utc",
        "window_kind": "calendar_month_utc",
        "timezone": "UTC",
        "current_window_started_at": _isoformat_utc(current_window_started_at),
        "current_window_ends_at": _isoformat_utc(next_reset_at),
        "next_reset_at": _isoformat_utc(next_reset_at),
        "next_reset_date": next_reset_at.date().isoformat(),
    }


def _subscription_reset_details(subscription: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(subscription, dict):
        return _unknown_reset_details()
    for value in _subscription_reset_candidates(subscription):
        normalized = _normalize_reset_mapping(value)
        if normalized["status"] == "known":
            return normalized
    return _unknown_reset_details(source="subscription_probe")


def _subscription_reset_candidates(subscription: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = [subscription]
    reset = subscription.get("reset")
    if isinstance(reset, dict):
        candidates.append(reset)
    for host in subscription.get("hosts") or []:
        if isinstance(host, dict):
            candidates.append(host)
            host_reset = host.get("reset")
            if isinstance(host_reset, dict):
                candidates.append(host_reset)
    return candidates


def _normalize_reset_mapping(data: dict[str, Any]) -> dict[str, Any]:
    current_window_started_at = _normalized_datetime(
        _first_present(
            data,
            "current_window_started_at",
            "current_period_started_at",
            "current_period_start",
            "period_start",
            "started_at",
        )
    )
    current_window_ends_at = _normalized_datetime(
        _first_present(
            data,
            "current_window_ends_at",
            "current_period_ends_at",
            "current_period_end",
            "period_end",
            "ends_at",
        )
    )
    next_reset_at = _normalized_datetime(
        _first_present(
            data,
            "next_reset_at",
            "reset_at",
            "renews_at",
            "renewal_at",
            "renewal_datetime",
        )
    )
    next_reset_date = _normalized_date(
        _first_present(
            data,
            "next_reset_date",
            "reset_date",
            "renews_on",
            "renewal_date",
            "renewal_day",
        )
    )
    if next_reset_date is None and next_reset_at is not None:
        next_reset_date = next_reset_at[:10]
    window_kind = _normalized_string(
        _first_present(data, "window_kind", "reset_window_kind")
    )
    timezone = _normalized_string(
        _first_present(data, "timezone", "reset_timezone", "tz")
    )
    source = _normalized_string(_first_present(data, "source", "reset_source"))
    known = any(
        (
            current_window_started_at,
            current_window_ends_at,
            next_reset_at,
            next_reset_date,
        )
    )
    return {
        "status": "known" if known else "unknown",
        "source": source or "subscription_probe",
        "window_kind": window_kind,
        "timezone": timezone,
        "current_window_started_at": current_window_started_at,
        "current_window_ends_at": current_window_ends_at,
        "next_reset_at": next_reset_at,
        "next_reset_date": next_reset_date,
    }


def _unknown_reset_details(*, source: str | None = None) -> dict[str, Any]:
    return {
        "status": "unknown",
        "source": source,
        "window_kind": None,
        "timezone": None,
        "current_window_started_at": None,
        "current_window_ends_at": None,
        "next_reset_at": None,
        "next_reset_date": None,
    }


def _normalized_string(value: Any) -> str | None:
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return None


def _normalized_datetime(value: Any) -> str | None:
    if isinstance(value, datetime):
        normalized = value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
        return _isoformat_utc(normalized)
    if isinstance(value, (int, float)):
        return _isoformat_utc(datetime.fromtimestamp(float(value), UTC))
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if not stripped or "T" not in stripped:
        return None
    candidate = stripped[:-1] + "+00:00" if stripped.endswith("Z") else stripped
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    normalized = parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return _isoformat_utc(normalized)


def _normalized_date(value: Any) -> str | None:
    if isinstance(value, datetime):
        normalized = value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
        return normalized.date().isoformat()
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), UTC).date().isoformat()
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if not stripped:
        return None
    if "T" in stripped:
        normalized = _normalized_datetime(stripped)
        if not normalized:
            return None
        return normalized[:10]
    try:
        return datetime.fromisoformat(stripped).date().isoformat()
    except ValueError:
        return None


def _isoformat_utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _openrouter_credits(config: AppConfig) -> dict[str, Any]:
    key = _secret(config, "OPENROUTER_API_KEY")
    if not key:
        return {
            "status": "not_configured",
            "configured": False,
            "reason": "OPENROUTER_API_KEY is not set",
            "source": None,
        }
    request = urllib.request.Request(
        "https://openrouter.ai/api/v1/credits",
        headers={
            "Authorization": f"Bearer {key}",
            "User-Agent": "delamain-assistant/0.1",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        return {
            "status": "unavailable",
            "configured": True,
            "reason": str(exc),
            "source": "openrouter_credits",
        }
    payload = data.get("data") if isinstance(data, dict) else None
    if not isinstance(payload, dict):
        return {
            "status": "unavailable",
            "configured": True,
            "reason": "OpenRouter credits response was invalid",
            "source": "openrouter_credits",
        }
    total = _first_present(payload, "total_credits", "credits")
    used = _first_present(payload, "total_usage", "usage")
    remaining = None
    if isinstance(total, (int, float)) and isinstance(used, (int, float)):
        remaining = max(0.0, float(total) - float(used))
    return {
        "status": "ok",
        "configured": True,
        "credits": total,
        "total_usage": used,
        "remaining_credits": remaining,
        "reason": None,
        "source": "openrouter_credits",
    }


def _first_present(data: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in data:
            return data[key]
    return None


def _anthropic_costs(config: AppConfig) -> dict[str, Any]:
    key = _secret(config, "ANTHROPIC_ADMIN_API_KEY")
    if not key:
        return {
            "status": "not_configured",
            "reason": "ANTHROPIC_ADMIN_API_KEY is not set",
            "source": "anthropic_admin_cost_report",
        }
    start, end = _month_bounds()
    query = urlencode({"starting_at": start, "ending_at": end, "bucket_width": "1d"})
    request = urllib.request.Request(
        f"https://api.anthropic.com/v1/organizations/cost_report?{query}",
        headers={
            "anthropic-version": "2023-06-01",
            "x-api-key": key,
            "User-Agent": "delamain-assistant/0.1",
        },
    )
    return _cost_report(request, source="anthropic_admin_cost_report")


def _openai_costs(config: AppConfig) -> dict[str, Any]:
    key = _secret(config, "OPENAI_ADMIN_API_KEY") or _secret(config, "OPENAI_API_KEY")
    if not key:
        return {
            "status": "not_configured",
            "reason": "OPENAI_ADMIN_API_KEY or OPENAI_API_KEY is not set",
            "source": "openai_organization_costs",
        }
    start = int(_month_start_datetime().timestamp())
    end = int(datetime.now(UTC).timestamp())
    query = urlencode({"start_time": start, "end_time": end, "bucket_width": "1d"})
    request = urllib.request.Request(
        f"https://api.openai.com/v1/organization/costs?{query}",
        headers={"Authorization": f"Bearer {key}"},
    )
    return _cost_report(request, source="openai_organization_costs")


def _cost_report(request: urllib.request.Request, *, source: str) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        return {"status": "unavailable", "reason": str(exc), "source": source}
    amount, currency = _sum_cost_amounts(data)
    return {
        "status": "ok",
        "reason": None,
        "amount_usd": amount,
        "currency": currency or "usd",
        "source": source,
    }


def _sum_cost_amounts(data: Any) -> tuple[float | None, str | None]:
    total = 0.0
    currency: str | None = None
    found = False

    def visit(value: Any) -> None:
        nonlocal total, currency, found
        if isinstance(value, dict):
            amount = value.get("amount")
            if isinstance(amount, dict) and isinstance(amount.get("value"), (int, float)):
                total += float(amount["value"])
                currency = str(amount.get("currency") or currency or "usd")
                found = True
            elif isinstance(amount, (int, float)):
                total += float(amount)
                found = True
            for key in ("amount_usd", "cost_usd", "total_cost_usd", "cost", "total_cost"):
                numeric = value.get(key)
                if isinstance(numeric, (int, float)):
                    total += float(numeric)
                    currency = currency or "usd"
                    found = True
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(data)
    return (round(total, 6), currency) if found else (None, None)


def _month_bounds() -> tuple[str, str]:
    start = _month_start_datetime()
    end = datetime.now(UTC) + timedelta(seconds=1)
    return (
        start.isoformat(timespec="seconds").replace("+00:00", "Z"),
        end.isoformat(timespec="seconds").replace("+00:00", "Z"),
    )


def _month_start_datetime() -> datetime:
    now = datetime.now(UTC)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _next_month_start_datetime(value: datetime) -> datetime:
    if value.month == 12:
        return value.replace(
            year=value.year + 1,
            month=1,
            day=1,
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )
    return value.replace(
        month=value.month + 1,
        day=1,
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )


def _secret(config: AppConfig, name: str) -> str | None:
    value = os.environ.get(name)
    if value and value.strip():
        return value.strip()
    for env_path in _env_paths(config):
        loaded = _secret_from_env_file(env_path, name)
        if loaded:
            return loaded
    return None


def _env_paths(config: AppConfig) -> list[Path]:
    paths = []
    explicit = os.environ.get("DELAMAIN_SECRETS_ENV")
    if explicit:
        paths.append(Path(explicit).expanduser())
    paths.append(Path(__file__).resolve().parent.parent / ".env")
    paths.append(config.database.path.parent / ".env")
    return paths


def _secret_from_env_file(path: Path, name: str) -> str | None:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    prefix = f"{name}="
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("export "):
            stripped = stripped.removeprefix("export ").strip()
        if not stripped or stripped.startswith("#") or not stripped.startswith(prefix):
            continue
        value = stripped.removeprefix(prefix).strip().strip('"').strip("'")
        return value.strip() or None
    return None
