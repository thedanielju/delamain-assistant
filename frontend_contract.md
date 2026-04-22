# DELAMAIN Frontend Contract

Last updated: 2026-04-22

This is the repo-local API contract for the DELAMAIN frontend. The deployed frontend should call same-origin `/api/...` behind Cloudflare Access. Local backend base URL is `http://127.0.0.1:8420/api`.

## Auth

Production API traffic is protected by Cloudflare Access. When a request reaches FastAPI without a valid Access JWT in `access_required` mode, the backend returns:

```json
{
  "detail": {
    "code": "auth_required",
    "message": "Missing Cloudflare Access JWT",
    "redirect_url": "https://<team>.cloudflareaccess.com/cdn-cgi/access/login?redirect_url=..."
  }
}
```

Cloudflare can still intercept before proxying to FastAPI. Treat either the JSON above or a Cloudflare login response as stale auth.

## Conversations

`GET /api/conversations`

Returns `ConversationOut[]`, ordered by `updated_at DESC`.

`POST /api/conversations`

Body:

```ts
{
  title?: string | null
  context_mode?: "normal" | "blank_slate"
  model_route?: string | null
  incognito_route?: boolean
  folder_id?: string | null
}
```

`GET /api/conversations/{conversation_id}`

Returns `ConversationOut`.

`PATCH /api/conversations/{conversation_id}`

Body:

```ts
{
  title?: string | null
  archived?: boolean | null
  folder_id?: string | null
}
```

`DELETE /api/conversations/{conversation_id}`

Returns `204`. Deletes messages, runs, events, and tool calls for the conversation.

`ConversationOut`:

```ts
{
  id: string
  title: string | null
  context_mode: "normal" | "blank_slate"
  model_route: string | null
  incognito_route: boolean
  sensitive_unlocked: boolean
  folder_id: string | null
  archived: boolean
  created_at: string
  updated_at: string
}
```

## Folders

`GET /api/folders`

Returns `FolderOut[]`, ordered by name.

`POST /api/folders`

Body: `{ name: string, parent_id?: string | null }`

`PATCH /api/folders/{folder_id}`

Body: `{ name?: string | null, parent_id?: string | null }`

`DELETE /api/folders/{folder_id}`

Returns `204`. Conversations in that folder are kept and set to `folder_id: null`; child folders are re-parented to `null`.

`FolderOut`:

```ts
{
  id: string
  name: string
  parent_id: string | null
  created_at: string
  updated_at: string
}
```

## Messages And Runs

`GET /api/conversations/{conversation_id}/messages`

Returns `MessageOut[]`, ordered by `created_at ASC`.

`POST /api/conversations/{conversation_id}/messages`

Body:

```ts
{
  content: string
  context_mode?: string | null
  model_route?: string | null
  incognito_route?: boolean | null
}
```

Returns immediately:

```ts
{
  message_id: string
  run_id: string
  status: "queued"
}
```

Ordering guarantee: the user message and run are persisted before this response. `run.queued` is emitted after that transaction. Very fast runs may emit later events before the browser opens SSE, so clients should use `Last-Event-ID` replay or refetch REST history after reconnect.

`MessageOut`:

```ts
{
  id: string
  conversation_id: string
  run_id: string | null
  role: "user" | "assistant" | "tool" | "system"
  content: string
  status: string
  created_at: string
  updated_at: string
}
```

`GET /api/conversations/{conversation_id}/runs`

Returns `RunOut[]`.

`GET /api/runs/{run_id}`

Returns `RunOut`.

`POST /api/runs/{run_id}/cancel`

Cancels a running run.

`POST /api/runs/{run_id}/retry`

Retries a failed or cancelled run.

Run statuses: `queued`, `running`, `waiting_approval`, `completed`, `failed`, `interrupted`, `cancelled`.

`RunOut`:

```ts
{
  id: string
  conversation_id: string
  user_message_id: string | null
  assistant_message_id: string | null
  status: string
  context_mode: string
  model_route: string | null
  incognito_route: boolean
  error_code: string | null
  error_message: string | null
  created_at: string
  started_at: string | null
  completed_at: string | null
}
```

## SSE

`GET /api/conversations/{conversation_id}/stream`

Streams all conversation events.

`GET /api/runs/{run_id}/stream`

Streams one run's events.

Both endpoints support `Last-Event-ID` and `last_event_id` query param. Events with `id > last_event_id` are replayed before the live subscription.

SSE wire format:

```text
id: 42
event: message.delta
data: {"payload": ...}
```

Known event payloads:

```ts
run.queued: { run_id: string, status?: string, position?: number }
run.started: { run_id: string, model_route?: string }
context.loaded: { items: unknown[] }
message.delta: { message_id: string, text: string }
message.completed: { message_id: string, finish_reason?: string }
tool.started: { assistant_message_id?: string, run_id?: string, tool_call_id: string, tool: string, name: string, arguments: unknown, args: unknown }
tool.output: { assistant_message_id?: string, run_id?: string, tool_call_id: string, stream?: "stdout" | "stderr", text: string, chunk: string }
tool.finished: { assistant_message_id?: string, run_id?: string, tool_call_id: string, status: string, duration_ms?: number, result_summary?: string, stdout?: string, stderr?: string }
model.usage: { run_id: string, model_route: string, model?: string, provider?: string, input_tokens?: number, output_tokens?: number, prompt_tokens?: number, completion_tokens?: number, premium_request_count?: number | null, estimated_cost?: number | null, estimated_cost_usd?: number | null }
permission.requested: { run_id: string, permission_id: string, kind: string, summary: string, details: unknown }
permission.resolved: { run_id?: string, permission_id: string, decision: string, resolver: string, note?: string | null }
conversation.title: { conversation_id?: string, title: string }
audit: { action: string, summary: string, [key: string]: unknown }
error: { code: string, message: string, details?: unknown }
run.completed: { run_id: string, status: string }
```

Frontend clients should render unknown event types as debug cards instead of crashing.

## Sensitive

`POST /api/conversations/{conversation_id}/sensitive/unlock`

Unlocks Sensitive for that conversation. Returns `{ sensitive_unlocked: true }`.

`POST /api/conversations/{conversation_id}/sensitive/lock`

Locks Sensitive for that conversation. Returns `{ sensitive_unlocked: false }`.

Conversations start locked. The model cannot unlock Sensitive by tool call. Sensitive lock/unlock/access attempts emit `audit` events.

## Usage

`GET /api/usage`

Returns a provider-oriented usage object:

```ts
{
  period: "current_month_utc"
  generated_at: string
  providers: UsageProvider[]
  subscriptions: SubscriptionSummary
}
```

`UsageProvider`:

```ts
{
  provider: "copilot" | "claude" | "codex" | "openrouter"
  label: string
  period: string
  unit: "premium_requests" | "calls" | "usd"
  used: number
  limit_or_credits: number | null
  percent_used: number | null
  status: string
  wired: boolean
  details: Record<string, unknown>
}
```

Provider notes:

- Copilot is backed by completed `github_copilot/*` rows in `model_calls` plus configured thresholds.
- OpenRouter credits are fetched when `OPENROUTER_API_KEY` exists.
- Anthropic organization costs are fetched when `ANTHROPIC_ADMIN_API_KEY` exists.
- OpenAI organization costs are fetched when `OPENAI_ADMIN_API_KEY` or `OPENAI_API_KEY` exists.
- Claude/Codex subscription readiness comes from CLI probes, not billing APIs.
- Missing credentials return stable `not_configured` fields.

`GET /api/usage/subscriptions`

Returns only the cached CLI subscription probe payload. `?refresh=true` bypasses cache.

```ts
{
  generated_at: string
  ttl_seconds: number
  providers: {
    codex: SubscriptionProvider
    claude: SubscriptionProvider
  }
}
```

`SubscriptionProvider`:

```ts
{
  provider: "codex" | "claude"
  label: string
  billing_kind: "subscription_auth"
  aggregate_status: "ok" | "degraded" | "unavailable"
  hosts: Array<{
    host: "local" | "winpc" | string
    local_hostname: string | null
    local_platform: string | null
    command: string
    status: "ok" | "degraded" | "unavailable"
    exit_code: number | null
    duration_ms: number
    checked_at: string
    authenticated: boolean | null
    auth_method: string | null
    subscription_type: string | null
    account: string | null
    version: string | null
    detail: string | null
  }>
}
```

## Syncthing

`GET /api/syncthing/summary`

Read-only summary sourced from Sync Guard reports under `llm-workspace/health/sync-guard/hosts/*/latest.json`.

```ts
{
  generated_at: string
  source: "sync_guard_reports"
  devices: Array<{
    host: string
    status: "ok" | "degraded" | "unavailable" | "unknown"
    timestamp: string | null
    syncthing_available: boolean
    conflict_count: number | null
    junk_count: number | null
    folders: Array<{
      folder_id: string
      state: string | null
      need_total_items: number | null
      need_bytes: number | null
      errors: number | null
      pull_errors: number | null
      global_total_items: number | null
      local_total_items: number | null
    }>
    connections: Array<{
      device_id: string
      connected: boolean
      address: string | null
      client_version: string | null
      paused: boolean
      at: string | null
    }>
    source: string
  }>
}
```

`GET /api/syncthing/conflicts`

```ts
{
  generated_at: string
  source: "sync_guard_reports"
  conflicts: Array<{
    path: string
    canonical_path: string | null
    folder_id: "vault-combo" | "7lf7x-urjpx" | "llm-workspace" | null
    devices: string[]
    mtimes: Record<string, string>
    reason: string | null
    review_dir: string | null
  }>
}
```

Conflict resolution actions are not exposed yet; current endpoints are read-only.

`POST /api/syncthing/conflicts/resolve`

Resolves one conflict file and writes reversible backups under the backend runtime directory, outside Syncthing:

```text
<database_dir>/syncthing-conflict-resolution-backups/
```

Body:

```ts
{
  path: string
  action: "keep_canonical" | "keep_conflict" | "keep_both" | "stage_review"
  note?: string | null
}
```

Actions:

- `keep_canonical`: back up the conflict file, then delete the conflict copy.
- `keep_conflict`: back up canonical and conflict, replace canonical with conflict contents, then delete the conflict copy.
- `keep_both`: back up the conflict file, copy conflict contents to a non-conflict sibling such as `note.conflict-copy.md`, then delete the conflict copy.
- `stage_review`: back up canonical/conflict and write a `resolution.json` manifest; source files are not changed.

Response:

```ts
{
  status: "resolved" | "staged"
  action: string
  path: string
  canonical_path: string | null
  result_path: string | null
  backup_dir: string
  backups: Array<{ label: string, source: string, backup: string }>
}
```

`7lf7x-urjpx` is the Syncthing folder ID for the Sensitive vault. Conflict resolution is an explicit REST/user action and is audited.

## Quick Actions

`GET /api/actions`

Returns `{ actions: ActionSpec[] }`.

Current action IDs:

```text
health.backend
health.helpers
ref.status
ref.reconcile_dry_run
vault_index.status
vault_index.build
sync_guard.status
subscription.codex_status
subscription.claude_status
subscription.gemini_status
winpc.subscription_codex_status
winpc.subscription_claude_status
winpc.hostname
winpc.date
```

`POST /api/actions/{action_id}`

Optional body: `{ conversation_id?: string | null }`. Returns an action run result with `status`, previews, artifact paths, `stdout_bytes`, `stderr_bytes`, `writes`, and `remote`.

Action statuses: `success`, `failed`, `timeout`, `denied`.

`GET /api/action-runs/{action_run_id}`

Returns persisted action metadata.

`GET /api/action-runs/{action_run_id}/stdout`

Returns full stdout as `text/plain`.

`GET /api/action-runs/{action_run_id}/stderr`

Returns full stderr as `text/plain`.

`GET /api/conversations/{conversation_id}/action-runs`

Returns action runs associated with that conversation.

## Permissions

`GET /api/runs/{run_id}/permissions`

Returns `PermissionOut[]`.

`POST /api/permissions/{permission_id}/resolve`

Body: `{ decision: "approved" | "denied", note?: string | null, resolver?: string | null }`

Returns `PermissionOut` and emits `permission.resolved`.

`PermissionOut`:

```ts
{
  id: string
  conversation_id: string
  run_id: string
  kind: string
  summary: string
  details_json: string
  status: "pending" | "resolved"
  decision: string | null
  resolver: string | null
  note: string | null
  created_at: string
  resolved_at: string | null
}
```

Model tools auto-run by default. Each tool can be configured with `approval_policy: "auto" | "confirm"`. In `confirm` mode, the run pauses at `waiting_approval`, emits `permission.requested`, and resumes after `POST /api/permissions/{permission_id}/resolve` approves it. Denial fails that tool call.

## Settings

`GET /api/settings`

Returns `{ settings: { context_mode, title_generation_enabled, model_default, copilot_budget_hard_override_enabled } }`.

`PATCH /api/settings`

Accepts `context_mode`, `title_generation_enabled`, `model_default`, and `copilot_budget_hard_override_enabled`.

`GET /api/settings/models`

Returns configured model routes and route families.

`GET /api/settings/budget`

Returns Copilot current-month premium request usage and soft/hard threshold state. The hard threshold is enforced unless `copilot_budget_hard_override_enabled` is true.

`GET /api/settings/tools`

Returns tool enabled state, risk metadata, and approval configurability.

```ts
{
  tools: Array<{
    name: string
    description: string
    enabled: boolean
    risk: "low" | "write" | "shell" | string
    approval_policy_default: "auto"
    approval_policy: "auto" | "confirm"
    approval_policy_options: ["auto", "confirm"]
  }>
}
```

`PATCH /api/settings/tools/{tool_name}`

Enables/disables a backend tool and/or changes its approval policy.

Body:

```ts
{
  enabled?: boolean
  approval_policy?: "auto" | "confirm"
  conversation_id?: string | null
}
```

## Context

`GET /api/context/current`

Returns active context items for `normal` or `blank_slate` mode.

`GET /api/context/files/system-context`

Returns editable system context file content and metadata.

`PATCH /api/context/files/system-context`

Writes system context with backup and optional audit.

`GET /api/context/files/short-term-continuity`

Returns editable short-term continuity file content and metadata.

`PATCH /api/context/files/short-term-continuity`

Writes short-term continuity with backup and optional audit.

## Workers

`GET /api/workers/types`

Worker types: `opencode`, `claude_code`, `codex_cli`, `gemini_cli`, `shell`, `winpc_shell`.

Launch flags:

- `claude_code`: `claude --dangerously-skip-permissions`
- `codex_cli`: `codex --yolo`
- `gemini_cli`: `gemini --yolo`

`GET /api/workers`

Lists workers; supports `status` and `conversation_id` filters.

`POST /api/workers`

Starts a worker.

`GET /api/workers/{worker_id}`

Returns worker metadata; `?refresh=true` checks liveness.

`POST /api/workers/{worker_id}/stop`

Graceful stop.

`DELETE /api/workers/{worker_id}`

Kill worker session.

`GET /api/workers/{worker_id}/output`

Returns captured tmux output.

## Health

`GET /api/health`

Returns backend status, SQLite health, LiteLLM status/version, config summary, Copilot budget summary, and deterministic helper availability.
