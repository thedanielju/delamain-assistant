# DELAMAIN Backend

Phase 2 backend vertical slice for DELAMAIN.

The backend runs on `serrano`, binds to `127.0.0.1:8420`, stores SQLite runtime data outside Syncthing at `/home/danielju/.local/share/delamain/conversations.sqlite`, and uses LiteLLM only as a model gateway.

Real model calls are disabled by default. Set `DELAMAIN_ENABLE_MODEL_CALLS=1` only for explicit Copilot/LiteLLM tests.

## Current Scope

Implemented through M8 worker session scaffold:

- M0 scaffold: config, migrations, SQLite path, health endpoint, LiteLLM known-bad version block.
- M1 conversations/runs/events: create/list/fetch/update/delete conversations, prompt submission, background runs, event persistence, SSE replay/live stream, retry/cancel endpoints.
- M2 LiteLLM router: route-family selection, result normalization, usage events, explicit fallback logging.
- M3 first tool loop: API-family-specific tool schemas, tool-call normalization, `get_now`, `delamain_ref`, `delamain_vault_index`, tool events, output caps, max-iteration guard.
- M4 narrow read-only policy: path canonicalization, allowed roots, explicit Sensitive lock/unlock endpoints, Sensitive access audit events, `read_text_file`, `list_directory`, and `search_vault`.
- M5 starter health tool: `get_health_status` aggregates deterministic helper/path status.
- M5.1 quick actions: fixed action registry, `/api/actions`, structured command execution, minimal environment, timeout handling, exit-code capture, full stdout/stderr artifacts in app data, preview fields, and audit events.
- M5.2 action-run retrieval: action metadata/list endpoints and owned stdout/stderr artifact reads without arbitrary file access.
- M6 settings/context: persisted settings, model/tool metadata, tool enable/disable enforcement, context file read/update endpoints, runtime backups, and audit events.
- M8 worker session scaffold: tmux-backed worker lifecycle, worker type registry, start/stop/kill/capture endpoints, DB persistence, conversation-scoped audit events.
- Post-M8 hardening: vault-index-backed `search_vault`, streaming-window `read_text_file`, SSE stale-subscriber cleanup, temp-table-free healthcheck, cached worker manager/registry, and symlink-tolerant owned artifact reads.
- Operational hardening: startup worker reconciliation, startup retention cleanup for action outputs/context backups, and Cloudflare Access JWT enforcement for deployed API traffic.
- Frontend contract support: conversation folders, usage aggregation, Claude/Codex subscription-auth probes, OpenRouter credits, read-only Syncthing status/conflict endpoints, permission approval REST/SSE shapes, and machine-readable stale-auth responses.

## Service

Installed as a user service on serrano:

```bash
systemctl --user status delamain-backend.service --no-pager
systemctl --user restart delamain-backend.service
journalctl --user -u delamain-backend.service -n 100 --no-pager
```

Service unit:

```text
/home/danielju/.config/systemd/user/delamain-backend.service
```

Non-secret environment file:

```text
/home/danielju/.config/delamain/backend.env
```

The service currently keeps real model calls disabled:

```text
DELAMAIN_ENABLE_MODEL_CALLS=0
```

The deployed serrano service currently keeps Cloudflare Access auth enabled:

```text
DELAMAIN_AUTH_MODE=access_required
```

Required Cloudflare Access env vars:

```text
DELAMAIN_AUTH_MODE=access_required
DELAMAIN_AUTH_ALLOWED_EMAIL=<Daniel's allowed Google email>
DELAMAIN_CF_ACCESS_TEAM_DOMAIN=https://<team-name>.cloudflareaccess.com
DELAMAIN_CF_ACCESS_AUDIENCE=<Cloudflare Access application AUD tag>
```

The backend validates the `Cf-Access-Jwt-Assertion` header against Cloudflare Access signing keys in `access_required` mode.

Public browser/API ingress is:

```text
https://term.danielju.com
  -> Cloudflare Access
  -> Cloudflare Tunnel
  -> nginx on serrano at http://127.0.0.1:8088
  -> /api/ to FastAPI at http://127.0.0.1:8420
  -> / to ttyd until the Next.js frontend replaces that route
```

Frontend code should use same-origin `/api/...` requests from `term.danielju.com`, not `127.0.0.1:8420`.

For local development without Cloudflare Access, explicitly set:

```text
DELAMAIN_AUTH_MODE=dev_local
```

## API Contract

Base URL: `http://127.0.0.1:8420/api`

Key endpoints:

```text
GET    /api/health
GET    /api/actions
POST   /api/actions/{action_id}
GET    /api/action-runs/{action_run_id}
GET    /api/action-runs/{action_run_id}/stdout
GET    /api/action-runs/{action_run_id}/stderr
GET    /api/usage
GET    /api/usage/subscriptions
GET    /api/syncthing/summary
GET    /api/syncthing/conflicts
GET    /api/folders
POST   /api/folders
PATCH  /api/folders/{folder_id}
DELETE /api/folders/{folder_id}
GET    /api/conversations
POST   /api/conversations
GET    /api/conversations/{conversation_id}
PATCH  /api/conversations/{conversation_id}
DELETE /api/conversations/{conversation_id}
POST   /api/conversations/{conversation_id}/sensitive/unlock
POST   /api/conversations/{conversation_id}/sensitive/lock
GET    /api/conversations/{conversation_id}/messages
POST   /api/conversations/{conversation_id}/messages
GET    /api/conversations/{conversation_id}/action-runs
GET    /api/conversations/{conversation_id}/runs
GET    /api/runs/{run_id}
GET    /api/runs/{run_id}/permissions
POST   /api/runs/{run_id}/cancel
POST   /api/runs/{run_id}/retry
POST   /api/permissions/{permission_id}/resolve
GET    /api/conversations/{conversation_id}/stream
GET    /api/runs/{run_id}/stream
GET    /api/settings
PATCH  /api/settings
GET    /api/settings/models
GET    /api/settings/budget
GET    /api/settings/tools
PATCH  /api/settings/tools/{tool_name}
GET    /api/context/current
GET    /api/context/files/system-context
PATCH  /api/context/files/system-context
GET    /api/context/files/short-term-continuity
PATCH  /api/context/files/short-term-continuity
GET    /api/workers/types
GET    /api/workers
POST   /api/workers
GET    /api/workers/{worker_id}
POST   /api/workers/{worker_id}/stop
DELETE /api/workers/{worker_id}
GET    /api/workers/{worker_id}/output
```

Submit-prompt flow:

1. `POST /api/conversations` creates a conversation.
2. `POST /api/conversations/{conversation_id}/messages` persists the user message and a queued run.
3. The response returns immediately with `message_id`, `run_id`, and `status=queued`.
4. Backend processing continues server-side.
5. REST history and SSE replay expose the completed result after reconnect.

Run statuses:

```text
queued
running
waiting_approval
completed
failed
interrupted
cancelled
```

SSE event names currently emitted:

```text
run.queued
run.started
context.loaded
message.delta
message.completed
tool.started
tool.output
tool.finished
model.usage
audit
error
run.completed
conversation.title
permission.requested
permission.resolved
```

SSE replay supports `Last-Event-ID`.
Tool events include `assistant_message_id` so frontend clients can attach tool cards to the correct assistant message even when a run starts with tool calls before assistant text.

Model calls:

- Real model calls are disabled by default.
- Enable only for an explicit smoke by setting `DELAMAIN_ENABLE_MODEL_CALLS=1`.
- Disable fallback for bounded route validation with `DELAMAIN_DISABLE_MODEL_FALLBACKS=1`.
- Model calls time out after `DELAMAIN_MODEL_TIMEOUT_SECONDS` seconds, default `30`.
- `github_copilot/gpt-5.4-mini` uses LiteLLM Responses API.
- Other configured routes use LiteLLM chat completions.

Filesystem/Sensitive policy:

- Allowed roots are `/home/danielju/Vault`, `/home/danielju/llm-workspace`, and `/home/danielju/Obsidian Sensitive`.
- Sensitive is locked by default per conversation.
- Conversation creation always starts with `sensitive_unlocked=false`; unlock is only through `POST /api/conversations/{conversation_id}/sensitive/unlock`.
- `POST /api/conversations/{conversation_id}/sensitive/lock` re-locks the conversation.
- Sensitive unlock, lock, allowed access, and denied access attempts emit `audit` events.
- The model cannot unlock Sensitive by tool call.
- `.env`, key/token/credential-like files, Syncthing config, private keys, and obvious binary/rich files are blocked.
- Implemented filesystem/shell tools: `read_text_file`, `list_directory`, `search_vault`, guarded `patch_text_file`, and guarded `run_shell`.
- `read_text_file` reads only the configured output window plus one byte and reports full file size from `stat()`.
- `search_vault` uses `delamain-vault-index query <term> --json` when available, filters returned paths through backend path policy, and falls back to direct scanning only if the helper/index path is unavailable.
- `patch_text_file` requires one exact preimage match in an allowed text file and writes a runtime backup outside Syncthing before replacing content. It is enabled by default; Sensitive files require the conversation's Sensitive unlock.
- `run_shell` accepts structured `argv` plus allowed `cwd`, rejects shell `-c` command strings, uses a minimal environment, caps output, enforces timeout, and denies Sensitive cwd/argv targets. It is disabled by default through tool settings.
- Implemented health tool: `get_health_status`.
- Broad `write_file`, `create_file`, and arbitrary overwrite remain intentionally unimplemented.

Quick actions:

- Actions are fixed operation specs, not arbitrary shell strings.
- Action execution uses structured `argv`, fixed/validated `cwd`, minimal environment, timeout handling, and exit-code capture.
- Full stdout/stderr are stored under `/home/danielju/.local/share/delamain/action-outputs/`.
- API responses include stdout/stderr previews and artifact paths.
- If `conversation_id` is supplied to `POST /api/actions/{action_id}`, action start/completion/timeout/denial audit events are emitted into that conversation.
- Sensitive paths are denied in action cwd/argv for M5.1, including relative path-like argv and `--flag=path` forms resolved against cwd.
- Spawn/runtime failures terminalize as structured `failed` results with `TOOL_EXECUTION_ERROR`; action runs should not remain stuck in `started`.
- Action output artifacts are explicitly required to live outside configured Vault, `llm-workspace`, and Sensitive roots.
- Action-run retrieval serves only stdout/stderr paths owned by persisted `action_runs` rows and refuses arbitrary file reads.
- Owned artifact reads validate the resolved target remains under the action-output root without rejecting legitimate symlinked path components.
- Initial action IDs:
  - `health.backend`
  - `health.helpers`
  - `ref.status`
  - `ref.reconcile_dry_run`
  - `vault_index.status`
  - `vault_index.build`
  - `sync_guard.status`
  - `subscription.codex_status`
  - `subscription.claude_status`
  - `winpc.subscription_codex_status`
  - `winpc.subscription_claude_status`
  - `winpc.hostname`
  - `winpc.date`

Settings:

- Settings are persisted in SQLite.
- `GET /api/settings` returns supported runtime settings.
- `PATCH /api/settings` currently accepts `context_mode`, `title_generation_enabled`, `model_default`, and `copilot_budget_hard_override_enabled`.
- `GET /api/settings/models` exposes configured model routes and route families.
- `GET /api/settings/budget` exposes approximate current-month Copilot request tracking from completed `github_copilot/*` model calls, plus soft/hard threshold status and whether the hard-threshold override is enabled.
- Copilot budget hard threshold enforcement skips Copilot routes and falls back to the configured paid route unless `copilot_budget_hard_override_enabled` is true. Soft threshold emits audit only.
- `GET /api/usage` exposes Copilot budget, completed call counts for Claude/Codex/OpenRouter, OpenRouter credits when `OPENROUTER_API_KEY` is configured, Anthropic organization cost reporting when `ANTHROPIC_ADMIN_API_KEY` is configured, OpenAI organization cost reporting when `OPENAI_ADMIN_API_KEY` or `OPENAI_API_KEY` is configured, and cached Claude/Codex CLI subscription-auth probes.
- `GET /api/usage/subscriptions` returns only the cached CLI subscription-auth probes and accepts `?refresh=true`.
- `GET /api/settings/tools` exposes tool names and enabled state.
- `PATCH /api/settings/tools/{tool_name}` enables or disables a backend tool.
- Disabled tools are omitted from model tool schemas and are denied if called in a tool loop.
- Settings/tool changes emit `audit` events when a `conversation_id` is supplied.

Context files:

- `GET /api/context/current` returns the active context item list for `normal` or `blank_slate` mode.
- Editable context files are:
  - `system-context`
  - `short-term-continuity`
- Context writes create timestamped backups under `/home/danielju/.local/share/delamain/context-backups/` before replacing existing files.
- Backup paths are required to stay outside Vault, `llm-workspace`, and Sensitive roots.
- Context writes emit `audit` events when a `conversation_id` is supplied.

Workers:

- Workers are named tmux sessions managed by the backend.
- `GET /api/workers/types` lists available worker types: `opencode`, `claude_code`, `shell`, and `winpc_shell`.
- `POST /api/workers` starts a new worker session; returns immediately with worker metadata.
- `GET /api/workers` lists all workers; filterable by `?status=` or `?conversation_id=`.
- `GET /api/workers/{worker_id}` returns worker metadata; `?refresh=true` checks tmux liveness.
- `POST /api/workers/{worker_id}/stop` sends Ctrl-C then `exit` to gracefully stop.
- `DELETE /api/workers/{worker_id}` kills the tmux session immediately.
- `GET /api/workers/{worker_id}/output?lines=N` captures the last N lines from the tmux pane.
- Serrano worker tmux socket: `/home/danielju/.local/share/delamain/workers.sock` (separate from the ttyd socket).
- `winpc_shell` starts/captures/stops/kills a WSL tmux session over `ssh winpc` with WSL cwd `/home/daniel`.
- Worker records persist in SQLite with status, type, host, tmux session/socket, conversation association, and timestamps.
- Worker start/stop/kill emit `audit` events when a `conversation_id` is supplied.
- Duplicate worker names are rejected while a worker with that name is running.
- Serrano workers use local tmux; `winpc_shell` uses the SSH/WSL tmux adapter.
- Worker manager and worker type registry are cached for the app lifespan.
- Backend startup reconciles persisted `running`/`starting`/`stopping` workers against live tmux sessions and marks dead sessions `stopped`.

Worker statuses:

```text
starting
running
stopping
stopped
failed
```

Maintenance:

- Startup cleanup removes action-output artifact directories older than `DELAMAIN_ACTION_OUTPUT_RETENTION_DAYS`, default `30`.
- Startup cleanup removes context backup files older than `DELAMAIN_CONTEXT_BACKUP_RETENTION_DAYS`, default `30`.
- SQLite metadata remains durable; old artifact URLs may return `404` after retention cleanup.

Auth deployment:

- Public access should stay behind Cloudflare Access and nginx/Cloudflare Tunnel.
- Cloudflare Access should use Google as the identity provider, Daniel's Google account as the only allowed identity, and a 30-day application/session duration.
- Passkey behavior is handled by Google account sign-in: Apple devices can use iCloud Keychain passkeys / Face ID / Touch ID where available, while non-Apple devices can use normal Google login.
- nginx must forward `CF-Access-JWT-Assertion` to FastAPI as `CF-Access-JWT-Assertion` or `Cf-Access-Jwt-Assertion`.
- Keep `DELAMAIN_AUTH_MODE=dev_local` until the Access application AUD tag and team domain are configured.

## Curl Examples

```bash
curl -s http://127.0.0.1:8420/api/health | jq
```

```bash
curl -s -X POST http://127.0.0.1:8420/api/conversations \
  -H 'Content-Type: application/json' \
  -d '{"title":"Smoke"}' | jq
```

```bash
curl -s -X POST http://127.0.0.1:8420/api/conversations/<conversation_id>/messages \
  -H 'Content-Type: application/json' \
  -d '{"content":"what time is it now?"}' | jq
```

```bash
curl -N http://127.0.0.1:8420/api/conversations/<conversation_id>/stream
```

```bash
curl -s -X POST http://127.0.0.1:8420/api/conversations/<conversation_id>/sensitive/unlock | jq
curl -s -X POST http://127.0.0.1:8420/api/conversations/<conversation_id>/sensitive/lock | jq
```

```bash
curl -s http://127.0.0.1:8420/api/actions | jq
```

```bash
curl -s -X POST http://127.0.0.1:8420/api/actions/ref.status \
  -H 'Content-Type: application/json' \
  -d '{"conversation_id":"<conversation_id>"}' | jq
```

```bash
curl -s http://127.0.0.1:8420/api/conversations/<conversation_id>/action-runs | jq
curl -s http://127.0.0.1:8420/api/action-runs/<action_run_id> | jq
curl -s http://127.0.0.1:8420/api/action-runs/<action_run_id>/stdout
```

```bash
curl -s http://127.0.0.1:8420/api/settings | jq
curl -s http://127.0.0.1:8420/api/settings/tools | jq
curl -s -X PATCH http://127.0.0.1:8420/api/settings/tools/get_now \
  -H 'Content-Type: application/json' \
  -d '{"enabled":false,"conversation_id":"<conversation_id>"}' | jq
```

```bash
curl -s http://127.0.0.1:8420/api/context/current | jq
curl -s http://127.0.0.1:8420/api/context/files/system-context | jq
curl -s -X PATCH http://127.0.0.1:8420/api/context/files/short-term-continuity \
  -H 'Content-Type: application/json' \
  -d '{"content":"Current continuity note.","conversation_id":"<conversation_id>"}' | jq
```

```bash
curl -s http://127.0.0.1:8420/api/workers/types | jq
curl -s http://127.0.0.1:8420/api/workers | jq
curl -s -X POST http://127.0.0.1:8420/api/workers \
  -H 'Content-Type: application/json' \
  -d '{"worker_type":"shell","name":"my-shell"}' | jq
curl -s http://127.0.0.1:8420/api/workers/<worker_id>?refresh=true | jq
curl -s http://127.0.0.1:8420/api/workers/<worker_id>/output?lines=50 | jq
curl -s -X POST http://127.0.0.1:8420/api/workers/<worker_id>/stop | jq
curl -s -X DELETE http://127.0.0.1:8420/api/workers/<worker_id> | jq
```

## Controlled Live Model Smoke

This may consume Copilot requests. Run only after explicit approval.

Text-only route smoke:

```bash
cd /home/danielju/delamain/backend
DELAMAIN_ENABLE_MODEL_CALLS=1 \
DELAMAIN_DISABLE_MODEL_FALLBACKS=1 \
/home/danielju/.local/share/delamain/backend-venv/bin/python scripts/live_model_smoke.py
```

One simple tool-call probe on the Responses route:

```bash
cd /home/danielju/delamain/backend
DELAMAIN_ENABLE_MODEL_CALLS=1 \
DELAMAIN_DISABLE_MODEL_FALLBACKS=1 \
/home/danielju/.local/share/delamain/backend-venv/bin/python scripts/live_model_smoke.py --tool-probe
```

The script prints the requested route, expected route family, run status, and persisted `model_calls` rows. It uses a temporary SQLite DB under `/tmp`.

If GitHub Copilot auth is not present under LiteLLM's normal local config path, the script refuses to start by default. Pass `--allow-device-flow` only when intentionally authenticating Copilot on `serrano`.

## Local Run

```bash
/home/danielju/.local/share/delamain/backend-venv/bin/uvicorn delamain_backend.main:app --host 127.0.0.1 --port 8420
```

## Tests

```bash
/home/danielju/.local/share/delamain/backend-venv/bin/python -m pytest
```
