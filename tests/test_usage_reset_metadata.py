from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from delamain_backend.main import create_app


class FixedDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        value = cls(2026, 4, 25, 15, 30, 0, tzinfo=UTC)
        if tz is None:
            return value.replace(tzinfo=None)
        return value.astimezone(tz)


def test_usage_endpoint_reports_copilot_monthly_reset_window(test_config, monkeypatch):
    _clear_usage_env(monkeypatch)
    monkeypatch.setattr("delamain_backend.usage.datetime", FixedDatetime)
    monkeypatch.setattr("delamain_backend.budget.datetime", FixedDatetime)
    monkeypatch.setattr(
        "delamain_backend.usage.subscription_status",
        lambda config: _subscription_payload(),
    )
    app = create_app(test_config)
    with TestClient(app) as client:
        asyncio.run(
            app.state.db.execute(
                """
                INSERT INTO model_calls(
                    id, run_id, model_route, api_family, status, created_at, completed_at
                )
                VALUES
                    (
                        'mc_copilot',
                        NULL,
                        'github_copilot/gpt-5.4-mini',
                        'responses',
                        'completed',
                        '2026-04-14T11:00:00.000Z',
                        '2026-04-14T11:05:00.000Z'
                    )
                """
            )
        )
        payload = client.get("/api/usage").json()

    copilot = {item["provider"]: item for item in payload["providers"]}["copilot"]
    assert copilot["used"] == 1
    assert copilot["limit_or_credits"] == 300
    assert copilot["details"]["last_observed_at"] == "2026-04-14T11:05:00.000Z"
    assert copilot["details"]["reset"] == {
        "status": "known",
        "source": "current_month_utc",
        "window_kind": "calendar_month_utc",
        "timezone": "UTC",
        "current_window_started_at": "2026-04-01T00:00:00Z",
        "current_window_ends_at": "2026-05-01T00:00:00Z",
        "next_reset_at": "2026-05-01T00:00:00Z",
        "next_reset_date": "2026-05-01",
    }


def test_usage_endpoint_marks_unknown_reset_metadata_when_unavailable(
    test_config, monkeypatch
):
    _clear_usage_env(monkeypatch)
    monkeypatch.setattr(
        "delamain_backend.usage.subscription_status",
        lambda config: _subscription_payload(
            claude_hosts=[
                {
                    "host": "local",
                    "status": "ok",
                    "subscription_type": "pro",
                }
            ],
            codex_hosts=[
                {
                    "host": "local",
                    "status": "ok",
                    "auth_method": "ChatGPT",
                }
            ],
        ),
    )
    app = create_app(test_config)
    with TestClient(app) as client:
        payload = client.get("/api/usage").json()

    providers = {item["provider"]: item for item in payload["providers"]}
    for provider in ("claude", "codex", "openrouter"):
        assert providers[provider]["details"]["reset"] == {
            "status": "unknown",
            "source": "subscription_probe" if provider in {"claude", "codex"} else None,
            "window_kind": None,
            "timezone": None,
            "current_window_started_at": None,
            "current_window_ends_at": None,
            "next_reset_at": None,
            "next_reset_date": None,
        }
    assert (
        providers["claude"]["details"]["subscription"]["hosts"][0]["subscription_type"]
        == "pro"
    )
    assert providers["codex"]["details"]["subscription"]["hosts"][0]["auth_method"] == "ChatGPT"


def test_usage_endpoint_normalizes_subscription_reset_metadata(
    test_config, monkeypatch
):
    _clear_usage_env(monkeypatch)
    monkeypatch.setattr(
        "delamain_backend.usage.subscription_status",
        lambda config: _subscription_payload(
            claude_hosts=[
                {
                    "host": "local",
                    "status": "ok",
                    "subscription_type": "pro",
                    "current_period_start": "2026-04-10T00:00:00Z",
                    "next_reset_at": "2026-05-10T00:00:00-04:00",
                    "timezone": "America/New_York",
                    "source": "claude_auth_status",
                }
            ]
        ),
    )
    app = create_app(test_config)
    with TestClient(app) as client:
        payload = client.get("/api/usage").json()

    claude = {item["provider"]: item for item in payload["providers"]}["claude"]
    assert claude["details"]["subscription"]["hosts"][0]["subscription_type"] == "pro"
    assert claude["details"]["reset"] == {
        "status": "known",
        "source": "claude_auth_status",
        "window_kind": None,
        "timezone": "America/New_York",
        "current_window_started_at": "2026-04-10T00:00:00Z",
        "current_window_ends_at": None,
        "next_reset_at": "2026-05-10T04:00:00Z",
        "next_reset_date": "2026-05-10",
    }


def _clear_usage_env(monkeypatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_ADMIN_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_ADMIN_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("DELAMAIN_SECRETS_ENV", raising=False)


def _subscription_payload(
    *,
    claude_hosts: list[dict] | None = None,
    codex_hosts: list[dict] | None = None,
) -> dict:
    return {
        "generated_at": "2026-04-25T15:30:00Z",
        "ttl_seconds": 60.0,
        "providers": {
            "claude": {
                "provider": "claude",
                "label": "Claude Code",
                "billing_kind": "subscription_auth",
                "aggregate_status": "ok",
                "hosts": claude_hosts or [],
            },
            "codex": {
                "provider": "codex",
                "label": "Codex",
                "billing_kind": "subscription_auth",
                "aggregate_status": "ok",
                "hosts": codex_hosts or [],
            },
        },
    }
