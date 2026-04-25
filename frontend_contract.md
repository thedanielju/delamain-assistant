---
tags: [project/delamain, backend, frontend, api-contract, phase-2]
aliases:
  - Frontend Contract
  - API Contract
---

# DELAMAIN Frontend Contract

Last updated: 2026-04-23

This document defines the complete backend API contract for a Phase 2 frontend implementation. The canonical backend runs on `serrano` at `http://127.0.0.1:8420/api`. Deployed frontends should call same-origin `/api/...` and should not depend on whether the current upstream hop is nginx, a Next.js rewrite, or direct localhost development. All responses are JSON unless otherwise noted.

## Authentication

Backend source now supports Cloudflare Access JWT validation but defaults to `DELAMAIN_AUTH_MODE=dev_local` for localhost/Tailscale development.

Production target:

- Cloudflare Access protects the production backend ingress and admin terminal surfaces.
- Google is the identity provider.
- Daniel's Google account is the only allowed identity.
- Session duration target is 30 days.
- Apple devices should use Google passkeys through iCloud Keychain / Face ID / Touch ID where available; non-Apple devices use normal Google login.
- nginx forwards `CF-Access-JWT-Assertion` to the FastAPI backend.
- FastAPI validates the JWT signature, issuer, Access application AUD tag, and allowed email when `DELAMAIN_AUTH_MODE=access_required`.

The frontend should not implement a separate password system. It should treat auth as an origin concern and assume same-origin authenticated requests once the production ingress is finalized.

When a request reaches FastAPI in `access_required` mode without a valid Cloudflare Access JWT, the backend returns:

```json
{
  "detail": {
    "code": "AUTH_REQUIRED",
    "message": "Missing Cloudflare Access JWT"
  }
}
```

Clients should treat auth codes case-insensitively and should not require `redirect_url` to exist. A backend-generated stale-auth response may include a `redirect_url`, but the current deployed backend response only guarantees `code` and `message`.

If Cloudflare itself intercepts before proxying to FastAPI, Cloudflare may still return its own login response. The machine-readable response above is guaranteed only for requests that reach the backend.

## Base URL

```text
http://127.0.0.1:8420/api
```

## Health

### GET /api/health

Returns backend status, SQLite health, LiteLLM version, config summary, helper availability, and cached system resource metrics.

Response:

```json
{
  "status": "ok",
  "sqlite": { "path": "...", "ok": true },
  "litellm": { "version": "1.83.8", "known_bad_blocked": true, "error": null },
  "config": {
    "host": "127.0.0.1",
    "port": 8420,
    "model_default": "github_copilot/gpt-5.4-mini",
    "model_calls_enabled": false
  },
  "budget": { "...": "same shape as GET /api/settings/budget copilot_budget" },
  "helpers": {
    "now": { "path": "...", "exists": true, "executable": true },
    "delamain_ref": { "path": "...", "exists": true, "executable": true },
    "delamain_vault_index": { "path": "...", "exists": true, "executable": true }
  },
  "system": {
    "delamain_backend": {
      "uptime_seconds": 1234,
      "rss_mb": 87.5,
      "cpu_percent_1min": 2.4,
      "num_threads": 19,
      "pid": 8420
    },
    "host": {
      "hostname": "serrano",
      "kernel": "6.8.0-59-generic",
      "load_avg": { "one": 0.42, "five": 0.37, "fifteen": 0.31 },
      "memory_total_mb": 31999.1,
      "memory_available_mb": 24782.4,
      "disks": [
        {
          "mountpoint": "/",
          "device": "/dev/sda1",
          "fstype": "ext4",
          "total_mb": 953356.1,
          "used_mb": 412883.7,
          "free_mb": 492098.5,
          "percent_used": 45.6
        }
      ]
    },
    "tmux_workers": {
      "count": 2,
      "rss_mb_total": 731.4
    }
  }
}
```

## Conversations

### GET /api/conversations

Returns all conversations ordered by `updated_at DESC`.

Response: `[ConversationOut, ...]`

### POST /api/conversations

Create a new conversation.

Request body:

| Field | Type | Default | Description |
|---|---|---|---|
| `title` | string or null | null | Optional title |
| `context_mode` | `"normal"` or `"blank_slate"` | `"normal"` | Context loading mode |
| `model_route` | string or null | null | Override model route |
| `incognito_route` | boolean | false | If true, use incognito/privacy route |
| `folder_id` | string or null | null | Optional sidebar folder assignment |

Response: `ConversationOut`

### GET /api/conversations/{conversation_id}

Response: `ConversationOut`

### PATCH /api/conversations/{conversation_id}

Request body:

| Field | Type | Description |
|---|---|---|
| `title` | string or null | Update title |
| `archived` | boolean or null | Archive/unarchive |
| `folder_id` | string or null | Move to folder, or clear with null |

Response: `ConversationOut`

### DELETE /api/conversations/{conversation_id}

Deletes the conversation and all associated messages, runs, events, and tool calls (cascade).

Response: `204 No Content`

### ConversationOut Shape

```json
{
  "id": "conv_...",
  "title": "My conversation",
  "context_mode": "normal",
  "model_route": null,
  "incognito_route": false,
  "sensitive_unlocked": false,
  "folder_id": null,
  "archived": false,
  "created_at": "2026-04-22T07:00:00.000Z",
  "updated_at": "2026-04-22T07:00:00.000Z"
}
```

## Folders

### GET /api/folders

Returns all conversation folders ordered by name.

Response: `[FolderOut, ...]`

### POST /api/folders

Request body:

| Field | Type | Description |
|---|---|---|
| `name` | string | Folder name |
| `parent_id` | string or null | Optional parent folder |

Response: `FolderOut`

### PATCH /api/folders/{folder_id}

Request body:

| Field | Type | Description |
|---|---|---|
| `name` | string or null | Rename folder |
| `parent_id` | string or null | Move folder or clear parent |

Response: `FolderOut`

### DELETE /api/folders/{folder_id}

Deletes the folder. Conversations in the folder are kept and receive `folder_id: null`; child folders also have `parent_id: null`.

Response: `204 No Content`

### FolderOut Shape

```json
{
  "id": "folder_...",
  "name": "School",
  "parent_id": null,
  "created_at": "...",
  "updated_at": "..."
}
```

## Messages and Prompt Submission

### GET /api/conversations/{conversation_id}/messages

Returns all messages for a conversation ordered by `created_at ASC`.

Response: `[MessageOut, ...]`

### POST /api/conversations/{conversation_id}/messages

Submit a user prompt. This is the primary interaction endpoint.

Request body:

| Field | Type | Default | Description |
|---|---|---|---|
| `content` | string (min 1 char) | required | The user message |
| `context_mode` | string or null | null | Override context mode for this run |
| `model_route` | string or null | null | Override model route for this run |
| `incognito_route` | boolean or null | null | Override incognito for this run |

Response (returns immediately, run executes in background):

```json
{
  "message_id": "msg_...",
  "run_id": "run_...",
  "status": "queued"
}
```

Frontend flow:
1. POST the prompt, receive `run_id`.
2. Connect to SSE stream to follow the run.
3. Run progresses through `queued` -> `running` -> `completed`/`failed`.
4. Messages and events accumulate during the run.

Ordering guarantee: the backend persists the user message and run before returning this response, emits `run.queued` after the transaction, and then enqueues background processing. A very fast run may emit `run.started`/deltas before the browser finishes opening SSE; clients should rely on SSE replay with `Last-Event-ID` or fetch REST history after reconnect.

### MessageOut Shape

```json
{
  "id": "msg_...",
  "conversation_id": "conv_...",
  "run_id": "run_...",
  "role": "user",
  "content": "what time is it?",
  "status": "completed",
  "created_at": "...",
  "updated_at": "..."
}
```

Roles: `user`, `assistant`, `tool`, `system`.

## Runs

### GET /api/conversations/{conversation_id}/runs

Returns all runs for a conversation.

### GET /api/runs/{run_id}

Returns a single run.

### POST /api/runs/{run_id}/cancel

Cancel a running run.

### POST /api/runs/{run_id}/retry

Retry a failed/cancelled run.

### Run Statuses

| Status | Description |
|---|---|
| `queued` | Submitted, waiting to start |
| `running` | Actively processing |
| `waiting_approval` | Paused for user approval (future) |
| `completed` | Finished successfully |
| `failed` | Finished with error |
| `interrupted` | Interrupted on startup recovery |
| `cancelled` | Cancelled by user |

### RunOut Shape

```json
{
  "id": "run_...",
  "conversation_id": "conv_...",
  "user_message_id": "msg_...",
  "assistant_message_id": "msg_...",
  "status": "completed",
  "context_mode": "normal",
  "model_route": "github_copilot/gpt-5.4-mini",
  "incognito_route": false,
  "error_code": null,
  "error_message": null,
  "created_at": "...",
  "started_at": "...",
  "completed_at": "..."
}
```

## SSE Streaming

### GET /api/conversations/{conversation_id}/stream

Stream all events for a conversation. Supports `Last-Event-ID` header and `last_event_id` query param for replay. Events with `id > Last-Event-ID` are replayed before live subscription.

### GET /api/runs/{run_id}/stream

Stream events for a specific run. Supports `Last-Event-ID` header and `last_event_id` query param for replay.

### Event Format

```text
id: 42
event: message.delta
data: {"payload": ...}
```

### Event Types

| Event | When | Key Payload Fields |
|---|---|---|
| `run.queued` | Run created | `run_id`, `status` |
| `run.started` | Run begins processing | `run_id` |
| `context.loaded` | Context files loaded | `items` (array of loaded context) |
| `message.delta` | Streaming assistant text | `message_id`, `text` |
| `message.completed` | Full assistant message finished | `message_id`, `finish_reason` |
| `tool.started` | Tool call begins | `assistant_message_id`, `tool_call_id`, `tool`, `name`, `arguments`, `args` |
| `tool.output` | Tool call output chunk | `assistant_message_id`, `tool_call_id`, `stream`, `text`, `chunk` |
| `tool.finished` | Tool call done | `assistant_message_id`, `tool_call_id`, `status`, `duration_ms`, `result_summary`, `stdout`, `stderr` |
| `model.usage` | Token usage | `run_id`, `model_route`, `prompt_tokens`, `completion_tokens`, `premium_request_count`, `estimated_cost` |
| `audit` | System audit event | `action`, `summary`, plus action-specific fields |
| `error` | Error occurred | `code`, `message` |
| `run.completed` | Run finished | `run_id`, `status` |
| `permission.requested` | Permission requested | `run_id`, `permission_id`, `kind`, `summary`, `details` |
| `permission.resolved` | Permission resolved | `permission_id`, `decision`, `resolver`, `note` |
| `conversation.title` | Deterministic title generated | `conversation_id`, `title` |

Compatibility aliases on tool events:

- `tool.started` includes both `tool`/`arguments` and `name`/`args`.
- `tool.output` includes both `text` and `chunk`.

## Sensitive Vault Access

### POST /api/conversations/{conversation_id}/sensitive/unlock

Unlock Sensitive vault access for this conversation. This is a user-initiated action; the model cannot unlock Sensitive by tool call.

Response: `{"sensitive_unlocked": true}`

### POST /api/conversations/{conversation_id}/sensitive/lock

Re-lock Sensitive vault access.

Response: `{"sensitive_unlocked": false}`

Both endpoints emit `audit` events. Conversations always start locked.

## Quick Actions

### GET /api/actions

Returns the list of registered deterministic actions.

Response:

```json
{
  "actions": [
    {
      "id": "health.backend",
      "label": "Backend health",
      "description": "Check whether the DELAMAIN backend user service is active.",
      "argv": ["/usr/bin/systemctl", "--user", "is-active", "delamain-backend.service"],
      "cwd": "/home/danielju/delamain/backend",
      "timeout_seconds": 5,
      "writes": false,
      "remote": false
    }
  ]
}
```

Available action IDs: `health.backend`, `health.helpers`, `ref.status`, `ref.reconcile_dry_run`, `vault_index.status`, `vault_index.build`, `sync_guard.status`, `subscription.codex_status`, `subscription.claude_status`, `subscription.gemini_status`, `winpc.subscription_codex_status`, `winpc.subscription_claude_status`, `winpc.subscription_gemini_status`, `winpc.hostname`, `winpc.date`.

### POST /api/actions/{action_id}

Execute an action. Returns `202 Accepted`.

Request body (optional):

| Field | Type | Description |
|---|---|---|
| `conversation_id` | string or null | Associate with a conversation for audit events |

Response:

```json
{
  "id": "actionrun_...",
  "action_id": "ref.status",
  "label": "Reference status",
  "status": "success",
  "error_code": null,
  "error_message": null,
  "exit_code": 0,
  "duration_ms": 168,
  "argv": ["..."],
  "cwd": "...",
  "writes": false,
  "remote": false,
  "stdout_path": "...",
  "stderr_path": "...",
  "stdout_bytes": 793,
  "stderr_bytes": 0,
  "stdout_preview": "...",
  "stderr_preview": "",
  "stdout_preview_truncated": false,
  "stderr_preview_truncated": false
}
```

Action statuses: `success`, `failed`, `timeout`, `denied`.

## Action Run Retrieval

### GET /api/action-runs/{action_run_id}

Returns the persisted action run record from SQLite (includes `conversation_id`, `argv_json`, timestamps).

### GET /api/action-runs/{action_run_id}/stdout

Returns the full stdout as `text/plain`.

### GET /api/action-runs/{action_run_id}/stderr

Returns the full stderr as `text/plain`.

### GET /api/conversations/{conversation_id}/action-runs

Returns all action runs associated with a conversation, ordered by `created_at DESC`.

## Usage

### GET /api/usage

Returns a single provider-oriented usage object for the Usage panel. Copilot is backed by persisted `model_calls` and configured thresholds. Claude, Codex, and OpenRouter also expose completed call counts from `model_calls`.

Billing/credit integrations:

- `OPENROUTER_API_KEY` enables OpenRouter credits via `GET https://openrouter.ai/api/v1/credits`.
- `ANTHROPIC_ADMIN_API_KEY` enables Anthropic organization cost reporting via `/v1/organizations/cost_report`. Anthropic requires an admin key; individual Claude accounts do not expose this API.
- `OPENAI_ADMIN_API_KEY` or `OPENAI_API_KEY` enables best-effort OpenAI organization cost reporting via `/v1/organization/costs`.
- Missing keys return stable `not_configured` shapes instead of frontend-specific branches.

Subscription/auth readiness is separate from billing. `/api/usage` includes a cached `subscriptions` object, and Claude/Codex provider rows include the same data under `details.subscription`. This runs fixed status probes (`codex login status`, `claude auth status`) on the backend host and WinPC WSL. The CLI status probes can report login/subscription readiness even when provider billing APIs are unavailable.

Response:

```json
{
  "period": "current_month_utc",
  "generated_at": "2026-04-22T20:00:00Z",
  "providers": [
    {
      "provider": "copilot",
      "label": "GitHub Copilot",
      "period": "current_month_utc",
      "unit": "premium_requests",
      "used": 12,
      "limit_or_credits": 300,
      "percent_used": 4,
      "status": "ok",
      "wired": true,
      "details": {
        "soft_threshold_percent": 60,
        "hard_threshold_percent": 90,
        "hard_override_enabled": false,
        "enforced": false,
        "tracked_model_calls": 12,
        "authoritative_premium_requests": 0,
        "estimated_premium_requests": 12,
        "usage_estimated": true,
        "usage_source": "estimated",
        "last_observed_at": "2026-04-22T20:00:00.000Z"
      }
    },
    {
      "provider": "claude",
      "label": "Claude",
      "period": "current_month_utc",
      "unit": "calls",
      "used": 0,
      "limit_or_credits": null,
      "percent_used": null,
      "status": "auth_ok_billing_not_configured",
      "wired": false,
      "details": {
        "reason": "ANTHROPIC_ADMIN_API_KEY is not set",
        "amount_usd": null,
        "currency": null,
        "source": "anthropic_admin_cost_report",
        "subscription": {
          "provider": "claude",
          "label": "Claude Code",
          "billing_kind": "subscription_auth",
          "aggregate_status": "ok",
          "hosts": [
            {
              "host": "local",
              "command": "claude auth status",
              "status": "ok",
              "authenticated": true,
              "auth_method": "claude.ai",
              "subscription_type": "pro",
              "account": "daniel@example.com",
              "version": "2.1.117 (Claude Code)",
              "detail": null
            }
          ]
        }
      }
    }
  ],
  "subscriptions": {
    "generated_at": "2026-04-22T20:00:00Z",
    "ttl_seconds": 60,
    "providers": {
      "codex": { "...": "same SubscriptionProvider shape" },
      "claude": { "...": "same SubscriptionProvider shape" }
    }
  }
}
```

Provider IDs are stable: `copilot`, `claude`, `codex`, `gemini`, `openrouter`.

Provider status values currently used: `ok`, `warn`, `soft_limit`, `hard_limit`, `auth_ok_billing_not_configured`, `not_configured`, `unavailable`.

### GET /api/usage/subscriptions

Returns only the cached subscription/auth probe payload. Query `?refresh=true` bypasses the in-memory TTL and runs probes immediately.

Response:

```json
{
  "generated_at": "2026-04-22T20:00:00Z",
  "ttl_seconds": 60,
  "providers": {
    "codex": {
      "provider": "codex",
      "label": "Codex",
      "billing_kind": "subscription_auth",
      "aggregate_status": "ok",
      "hosts": [
        {
          "host": "local",
          "local_hostname": "Daniels-MacBook-Pro.local",
          "local_platform": "darwin",
          "command": "codex login status",
          "status": "ok",
          "exit_code": 0,
          "duration_ms": 32,
          "checked_at": "2026-04-22T20:00:00Z",
          "authenticated": true,
          "auth_method": "Logged in using ChatGPT",
          "subscription_type": null,
          "account": null,
          "version": "codex-cli 0.122.0",
          "detail": null
        }
      ]
    }
  }
}
```

`aggregate_status` and per-host `status` values: `ok`, `degraded`, `unavailable`. `degraded` includes a capped `detail` string suitable for a troubleshooting expander. Current known limitation: Codex CLI exposes ChatGPT login readiness but not a first-class plan name; Claude Code exposes `subscriptionType` when `claude auth status` returns it; Gemini CLI currently uses non-invasive OAuth credential presence as the auth probe.

## Syncthing

These endpoints are read-only. First slice reads Sync Guard reports under `llm-workspace/health/sync-guard/hosts/*/latest.json` instead of contacting every Syncthing REST API directly.

### GET /api/syncthing/summary

Response:

```json
{
  "generated_at": "2026-04-22T20:00:00Z",
  "source": "sync_guard_reports",
  "devices": [
    {
      "host": "serrano",
      "status": "ok",
      "timestamp": "2026-04-22T16:16:03",
      "syncthing_available": true,
      "conflict_count": 0,
      "junk_count": 0,
      "folders": [
        {
          "folder_id": "llm-workspace",
          "state": "idle",
          "need_total_items": 0,
          "need_bytes": 0,
          "errors": 0,
          "pull_errors": 0,
          "global_total_items": 678,
          "local_total_items": 678
        }
      ],
      "connections": [
        {
          "device_id": "...",
          "connected": true,
          "address": "192.168.1.192:22000",
          "client_version": "v2.0.16",
          "paused": false,
          "at": "2026-04-22T16:16:03-04:00"
        }
      ],
      "source": "/home/danielju/llm-workspace/health/sync-guard/hosts/serrano/latest.json"
    }
  ]
}
```

Expected devices with no report may appear with `status: "unknown"` and `source: "expected_device"`.

### GET /api/syncthing/conflicts

Response:

```json
{
  "generated_at": "2026-04-22T20:00:00Z",
  "source": "sync_guard_reports",
  "conflicts": [
    {
      "path": "/home/danielju/llm-workspace/foo.sync-conflict-...",
      "canonical_path": "/home/danielju/llm-workspace/foo.md",
      "folder_id": "llm-workspace",
      "devices": ["serrano"],
      "mtimes": { "serrano": "2026-04-22T20:00:00Z" },
      "reason": "manual text merge required",
      "review_dir": "/home/danielju/llm-workspace/health/sync-guard/review/..."
    }
  ]
}
```

Folder IDs of interest: `vault-combo`, `7lf7x-urjpx`, `llm-workspace`.

`7lf7x-urjpx` is the Syncthing folder ID for the Sensitive vault.

### POST /api/syncthing/conflicts/resolve

Resolve one conflict file. Backups are written outside Syncthing under the backend runtime directory: `<database_dir>/syncthing-conflict-resolution-backups/`.

Request body:

| Field | Type | Description |
|---|---|---|
| `path` | string | Conflict file path |
| `action` | `"keep_canonical"`, `"keep_conflict"`, `"keep_both"`, or `"stage_review"` | Resolution action |
| `note` | string or null | Optional note stored in the backup manifest |

Actions:

- `keep_canonical`: back up the conflict file, then delete the conflict copy.
- `keep_conflict`: back up canonical and conflict, replace canonical with conflict contents, then delete the conflict copy.
- `keep_both`: back up the conflict file, copy conflict contents to a non-conflict sibling such as `note.conflict-copy.md`, then delete the conflict copy.
- `stage_review`: back up canonical/conflict and write a `resolution.json` manifest; source files are not changed.

Response:

```json
{
  "status": "resolved",
  "action": "keep_both",
  "path": "...",
  "canonical_path": "...",
  "result_path": "...",
  "backup_dir": "/home/danielju/.local/share/delamain/syncthing-conflict-resolution-backups/...",
  "backups": [
    { "label": "conflict", "source": "...", "backup": "..." }
  ]
}
```

## Permissions

Current tool policy auto-runs enabled tools by default. Each tool can be configured with `approval_policy: "auto" | "confirm"`. `confirm` pauses the run at `waiting_approval`, emits `permission.requested`, and resumes after approval through `POST /api/permissions/{permission_id}/resolve`.

### GET /api/runs/{run_id}/permissions

Returns all permissions associated with a run.

Response: `[PermissionOut, ...]`

### POST /api/permissions/{permission_id}/resolve

Request body:

| Field | Type | Description |
|---|---|---|
| `decision` | `"approved"` or `"denied"` | User decision |
| `note` | string or null | Optional note |
| `resolver` | string or null | Resolver label, defaults to `"user"` |

Response: `PermissionOut`. Emits `permission.resolved`.

### PermissionOut Shape

```json
{
  "id": "perm_...",
  "conversation_id": "conv_...",
  "run_id": "run_...",
  "kind": "tool",
  "summary": "Approve shell command",
  "details_json": "{}",
  "status": "pending",
  "decision": null,
  "resolver": null,
  "note": null,
  "created_at": "...",
  "resolved_at": null
}
```

## Settings

### GET /api/settings

Returns current runtime settings.

Response:

```json
{
  "settings": {
    "context_mode": "normal",
    "title_generation_enabled": true,
    "model_default": "github_copilot/gpt-5.4-mini",
    "task_model": "github_copilot/claude-haiku-4.5",
    "copilot_budget_hard_override_enabled": false
  }
}
```

### PATCH /api/settings

Update runtime settings.

Request body:

| Field | Type | Description |
|---|---|---|
| `values` | object | Key-value pairs of settings to update |
| `conversation_id` | string or null | For audit event association |

Supported keys: `context_mode` (`"normal"` or `"blank_slate"`), `title_generation_enabled` (boolean), `model_default` (must be a configured route), `task_model` (must be a configured route, used by worker summaries/background helper tasks), and `copilot_budget_hard_override_enabled` (boolean).

### GET /api/settings/models

Returns configured model routes and route families.

Response:

```json
{
  "default": "github_copilot/gpt-5.4-mini",
  "fallback_high_volume": "github_copilot/gpt-5-mini",
  "fallback_cheap": "github_copilot/claude-haiku-4.5",
  "paid_fallback": "openrouter/deepseek/deepseek-v3.2"
}
```

### GET /api/settings/budget

Returns Copilot request tracking for the current UTC month. This counts completed persisted `model_calls` rows whose route starts with `github_copilot/`. Newer rows may include provider-observed premium request counts; legacy rows and rows without provider count metadata fall back to an estimated one premium request per completed Copilot call.

Response:

```json
{
  "copilot_budget": {
    "period": "current_month_utc",
    "used_premium_requests": 1,
    "monthly_premium_requests": 300,
    "percent_used": 0.33,
    "tracked_model_calls": 1,
    "authoritative_premium_requests": 0,
    "estimated_premium_requests": 1,
    "usage_estimated": true,
    "usage_source": "estimated",
    "last_observed_at": "2026-04-22T20:00:00.000Z",
    "soft_threshold_percent": 60,
    "hard_threshold_percent": 90,
    "status": "ok",
    "hard_override_enabled": false,
    "enforced": false
  }
}
```

Soft budget threshold emits audit only. Hard threshold skips Copilot routes and falls back to the configured paid route unless `copilot_budget_hard_override_enabled` is true.

### GET /api/settings/tools

Returns all backend tools, enabled state, risk metadata, and approval policy.

Response:

```json
{
  "tools": [
    {
      "name": "get_now",
      "description": "Return Daniel's live wall-clock time.",
      "enabled": true,
      "risk": "low",
      "approval_policy_default": "auto",
      "approval_policy": "auto",
      "approval_policy_options": ["auto", "confirm"]
    }
  ]
}
```

`patch_text_file` is enabled by default with `risk: "write"`. `run_shell` is available but disabled by default with `risk: "shell"`. Tools default to autonomous `approval_policy: "auto"`; the UI can set `confirm` for a specific tool when Daniel wants an approval stop.

### PATCH /api/settings/tools/{tool_name}

Enable/disable a tool and/or update approval policy.

Request body:

| Field | Type | Description |
|---|---|---|
| `enabled` | boolean or omitted | New enabled state |
| `approval_policy` | `"auto"` or `"confirm"` | Tool approval policy |
| `conversation_id` | string or null | For audit event association |

Disabled tools are omitted from model schemas and denied if called. `confirm` tools emit `permission.requested` and set the run to `waiting_approval` until resolved.

## Context Files

### GET /api/context/current

Query param: `context_mode=normal` or `context_mode=blank_slate`.

Returns the list of context items that would be loaded for a run.

Response:

```json
{
  "context_mode": "normal",
  "items": [
    {
      "path": "/home/danielju/llm-workspace/context/system-context.md",
      "mode": "system_context",
      "included": true,
      "missing": false,
      "byte_count": 9522,
      "sha256": "..."
    },
    {
      "path": "/home/danielju/llm-workspace/context/short-term/continuity.md",
      "mode": "short_term_continuity",
      "included": false,
      "missing": true,
      "byte_count": null,
      "sha256": null
    }
  ]
}
```

### GET /api/context/files/{file_id}

Read a context file. Valid file IDs: `system-context`, `short-term-continuity`.

Response:

```json
{
  "id": "system-context",
  "mode": "system_context",
  "path": "...",
  "exists": true,
  "content": "...",
  "byte_count": 9522,
  "sha256": "..."
}
```

### PATCH /api/context/files/{file_id}

Write a context file. Creates a timestamped backup before replacing.

Request body:

| Field | Type | Description |
|---|---|---|
| `content` | string | New file content |
| `conversation_id` | string or null | For audit event association |

Returns the updated file metadata (same shape as GET).

## Workers

### GET /api/workers/types

Returns available worker types.

Response:

```json
{
  "types": [
    {
      "id": "shell",
      "label": "Shell",
      "description": "Start a plain bash shell session on serrano.",
      "command_template": ["/bin/bash", "--login"],
      "host": "serrano"
    },
    {
      "id": "opencode",
      "label": "OpenCode",
      "description": "Start an OpenCode agent session on serrano.",
      "command_template": ["/home/danielju/.local/bin/opencode"],
      "host": "serrano"
    },
    {
      "id": "claude_code",
      "label": "Claude Code",
      "description": "Start a Claude Code agent session on serrano with permissions bypassed.",
      "command_template": ["claude", "--dangerously-skip-permissions"],
      "host": "serrano"
    },
    {
      "id": "codex_cli",
      "label": "Codex CLI",
      "description": "Start a Codex CLI agent session on serrano in YOLO mode.",
      "command_template": ["codex", "--yolo"],
      "host": "serrano"
    },
    {
      "id": "gemini_cli",
      "label": "Gemini CLI",
      "description": "Start a Gemini CLI agent session on serrano in YOLO mode.",
      "command_template": ["gemini", "--yolo"],
      "host": "serrano"
    },
    {
      "id": "winpc_shell",
      "label": "WinPC Shell",
      "description": "Start a plain bash shell session in WSL tmux on winpc.",
      "command_template": ["/bin/bash", "--login"],
      "host": "winpc"
    },
    {
      "id": "winpc_opencode",
      "label": "WinPC OpenCode",
      "description": "Start an OpenCode agent session in WSL tmux on winpc.",
      "command_template": ["/home/daniel/.local/bin/opencode"],
      "host": "winpc"
    },
    {
      "id": "winpc_claude_code",
      "label": "WinPC Claude Code",
      "description": "Start a Claude Code agent session in WSL tmux on winpc with permissions bypassed.",
      "command_template": ["claude", "--dangerously-skip-permissions"],
      "host": "winpc"
    },
    {
      "id": "winpc_codex_cli",
      "label": "WinPC Codex CLI",
      "description": "Start a Codex CLI agent session in WSL tmux on winpc in YOLO mode.",
      "command_template": ["/home/daniel/.local/bin/codex-wsl", "--yolo"],
      "host": "winpc"
    },
    {
      "id": "winpc_gemini_cli",
      "label": "WinPC Gemini CLI",
      "description": "Start a Gemini CLI agent session in WSL tmux on winpc in YOLO mode.",
      "command_template": ["gemini", "--yolo"],
      "host": "winpc"
    }
  ]
}
```

### GET /api/workers

List all workers. Filterable by query params.

Query params:

| Param | Type | Description |
|---|---|---|
| `status` | string or null | Filter by status |
| `conversation_id` | string or null | Filter by conversation |

Response:

```json
{
  "workers": [WorkerOut, ...]
}
```

### POST /api/workers

Start a new worker session. Returns `202 Accepted`.

Request body:

| Field | Type | Default | Description |
|---|---|---|---|
| `worker_type` | string | required | One of the registered type IDs |
| `name` | string or null | auto-generated | Human-readable name (must be unique among running workers) |
| `conversation_id` | string or null | null | Associate with a conversation for audit events |

Response: `WorkerOut`

### GET /api/workers/{worker_id}

Get worker details. Add `?refresh=true` to check tmux liveness and update status if the session has died.

Response: `WorkerOut`

### PATCH /api/workers/{worker_id}

Rename a worker. The backend rejects an empty name and rejects duplicate names among workers that are currently `running` or `starting`. When the worker has an associated `conversation_id`, this emits a `worker.renamed` audit event.

Request body:

| Field | Type | Description |
|---|---|---|
| `name` | string | New human-readable worker name |

Response: `WorkerOut`

### POST /api/workers/{worker_id}/stop

Graceful stop: sends `Ctrl-C` then `exit` to the tmux session. Returns current status. If the session is still alive after the stop attempt, status becomes `stopping`.

Response: `WorkerOut`

### DELETE /api/workers/{worker_id}

Force kill: destroys the tmux session immediately.

Response: `WorkerOut`

### GET /api/workers/{worker_id}/output

Capture the current tmux pane content.

Query params:

| Param | Type | Default | Description |
|---|---|---|---|
| `lines` | integer (1-2000) | 200 | Number of lines to capture |

Response:

```json
{
  "worker_id": "worker_...",
  "name": "my-shell",
  "alive": true,
  "lines_requested": 200,
  "output": "danielju@serrano:~$ ..."
}
```

### WS /api/workers/{worker_id}/pty

Open an interactive worker terminal bridge backed by the worker's existing tmux session and socket metadata. This endpoint is for live terminal UI only; `GET /api/workers/{worker_id}/output` remains the REST snapshot/manual fallback.

Query params:

| Param | Type | Default | Description |
|---|---|---|---|
| `snapshot` | boolean | true | Send an initial bounded `tmux capture-pane` snapshot |
| `lines` | integer (1-2000) | 200 | Initial snapshot line count |

Server-to-client text frames are JSON:

```json
{ "type": "snapshot", "data": "initial pane text..." }
{ "type": "data", "data": "new pane text..." }
{ "type": "error", "message": "Worker is not running (status=stopped)" }
```

Client-to-server input frames should be JSON:

```json
{ "type": "input", "data": "echo hello\r" }
```

The backend closes cleanly with an error frame when the worker is missing, not running, or the tmux session is gone. Multiple clients may observe the same worker; input is serialized through the worker manager's tmux send-keys path. WinPC workers continue through `ssh winpc` -> `wsl.exe tmux ...`.

### WorkerOut Shape

```json
{
  "id": "worker_bd039d15e2eb",
  "status": "running",
  "name": "my-shell",
  "worker_type": "shell",
  "host": "serrano",
  "tmux_session": "dw-worker_bd039d15e2eb",
  "tmux_socket": "/home/danielju/.local/share/delamain/workers.sock",
  "conversation_id": null,
  "command": "/bin/bash --login",
  "pid": null,
  "exit_code": null,
  "error_message": null,
  "stopped_at": null,
  "metadata": {},
  "created_at": "2026-04-22T07:29:38.841Z",
  "updated_at": "2026-04-22T07:29:38.841Z"
}
```

### Worker Statuses

| Status | Description |
|---|---|
| `starting` | tmux session creation in progress |
| `running` | tmux session is alive |
| `stopping` | Graceful stop sent, session still alive |
| `stopped` | Session terminated |
| `failed` | Session creation or execution failed |

## Error Responses

All error responses use standard HTTP status codes with a JSON body:

```json
{
  "detail": "Human-readable error message"
}
```

Common codes:

| Code | Meaning |
|---|---|
| 400 | Bad request / validation error |
| 403 | Policy denied (Sensitive, path policy) |
| 404 | Resource not found |
| 500 | Internal server error |

## Audit Events

Many endpoints emit `audit` events into the SSE stream when a `conversation_id` is provided. The frontend can display these as system notifications.

Audit event payload shape:

```json
{
  "action": "worker.started",
  "summary": "Worker my-shell (shell) started",
  "worker_id": "worker_...",
  "name": "my-shell",
  "worker_type": "shell",
  "status": "running"
}
```

Known audit actions:

| Action | Source |
|---|---|
| `sensitive.unlocked` | Sensitive unlock |
| `sensitive.locked` | Sensitive lock |
| `sensitive.access_allowed` | Tool accessed Sensitive |
| `sensitive.access_denied` | Tool denied Sensitive |
| `quick_action.started` | Action execution started |
| `quick_action.completed` | Action completed |
| `quick_action.failed` | Action failed |
| `quick_action.timeout` | Action timed out |
| `quick_action.denied` | Action policy denied |
| `settings.updated` | Settings changed |
| `settings.tool_updated` | Tool enabled/disabled |
| `context.file_updated` | Context file written |
| `model.reported_route_mismatch` | Provider route mismatch |
| `worker.started` | Worker started |
| `worker.failed` | Worker start failed |
| `worker.stop_requested` | Worker stop initiated |
| `worker.killed` | Worker force killed |

## Frontend Implementation Notes

### Conversation Page

1. Fetch conversation and messages on load.
2. Connect to conversation SSE stream for live updates.
3. Render messages by role; tool calls can be collapsible.
4. Show run status indicator (spinner for `queued`/`running`).
5. Provide cancel/retry buttons based on run status.

### Settings Panel

1. Fetch settings, models, and tools on load.
2. Allow toggling context mode, title generation, and model default.
3. Allow enabling/disabling individual tools.
4. Show context file content with edit capability.

### Actions Panel

1. Fetch action list on load.
2. Provide run buttons per action.
3. Show action run results inline with stdout/stderr previews.
4. Link to full stdout/stderr via artifact endpoints.

### Workers Panel

1. Fetch worker types and active workers on load.
2. Provide start buttons per type with optional name input.
3. Show worker status with refresh capability.
4. Provide stop/kill buttons.
5. Show captured pane output (polling or on-demand).
6. Workers panel is useful for launching background agent sessions that work independently of the main conversation.

### Sensitive Gate

1. Show a lock/unlock toggle per conversation.
2. Locked is the default; unlocking requires explicit user action.
3. Display audit events for Sensitive access attempts.
