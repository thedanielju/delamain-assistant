# DELAMAIN AGENTS

## Purpose
This repository is DELAMAIN, Daniel Ju's single-user personal LLM assistant.

DELAMAIN is not a generic web app. The hard parts are policy, orchestration, and cross-system correctness:
- backend-owned agent loop
- deterministic tool execution
- Sensitive vault security boundaries
- multi-provider model routing and budget fallback
- SSE replay/live-stream correctness
- tmux-backed worker orchestration across `serrano` and `winpc`
- subscription probes and Syncthing conflict handling

Treat this repo as a high-context system where small changes can create subtle drift across backend, frontend, and infrastructure.

## Canonical Paths
- Canonical Mac repo: `/Users/danielju/Desktop/delamain-assistant.nosync`
- Public hostname: `https://term.danielju.com`
- Production frontend origin on `serrano`: `127.0.0.1:3000`
- Production backend origin on `serrano`: `127.0.0.1:8420`
- Public traffic must not depend on the dev-local sidecar at `127.0.0.1:8421`
- `chat.danielju.com` has been deleted and must not be used

## Project Overview
Major backend subsystems:
- `delamain_backend/main.py`: app assembly, startup/shutdown, auth middleware, startup recovery
- `delamain_backend/api/`: REST API and contract surface
- `delamain_backend/agent/`: run manager, context loading, model loop, route fallback
- `delamain_backend/tools/`: deterministic tool registry and execution
- `delamain_backend/security/`: path-policy enforcement and Sensitive protection
- `delamain_backend/events/`: EventBus, SSE replay/live streaming
- `delamain_backend/workers/`: tmux/SSH worker orchestration
- `delamain_backend/actions/`: deterministic direct actions
- `delamain_backend/db/`: schema and migrations
- `delamain_backend/{budget,usage,subscription_status,syncthing_status}.py`: operational accounting/status subsystems

Major frontend subsystems:
- `frontend/app/`: Next.js app entrypoints
- `frontend/components/chat/`: main product UI and panels
- `frontend/hooks/useDelamainBackend.ts`: client-side orchestration, SSE handling, optimistic state
- `frontend/lib/`: API client, backend types, UI mappers, SSE helpers

Config, scripts, tests, docs:
- `config/defaults.yaml`: backend defaults, model routes, auth/runtime/budget config
- `frontend/.env.local.example`: frontend env example
- `delamain_ref/`: repo-owned deterministic reference ingestion and vault indexing helper package
- `scripts/helper_wrappers/`: thin runtime wrappers for `llm-workspace/bin/delamain-ref` and `delamain-vault-index`
- `scripts/deploy_serrano.sh`: canonical serrano deploy script for backend, frontend, helper wrappers, vault-index rebuild, checks, and service restarts
- `scripts/live_model_smoke.py`: guarded live model smoke
- `tests/`: backend regression/integration suite
- `frontend_contract.md`: backend/frontend API contract reference
- `docs/vault-graph-contract.md`: Vault graph/context contract reference
- `README.md`: repo-local overview

Out-of-repo infrastructure:
- nginx, Cloudflare Tunnel, Cloudflare Access, and systemd unit files are not source-controlled here
- verify live infra behavior against host config or vault docs before assuming anything

Obsidian project docs:
- Daniel's DELAMAIN vault folder (with subfolders) at /Users/danielju/Desktop/Obsidian.nosync/Vault/Projects/DELAMAIN is a secondary human-reference source, not default bulk context
- use targeted docs such as `current-state.md` or `frontend-contract.md` when the task touches live topology, deployment reality, or planning context that is not fully captured in-repo
- do not crawl the full Obsidian project folder by default; while it is useful, only crawl when absolutely appropriate and user prompts seem to indicate read/write to said subfolder (and subfolders).

## Behaviors That Must Be Preserved
- Sensitive vault stays locked by default and cannot be casually exposed
- deterministic tools/actions remain deterministic and policy-bound
- public API response shapes stay stable unless the task explicitly requires contract change
- SSE event naming, replay semantics, and stream ordering remain compatible with the frontend
- worker/tmux/SSH coordination remains correct across `serrano` and `winpc`
- model routing, budget thresholds, and fallback semantics remain intentional
- production public ingress remains `term.danielju.com` with Cloudflare Access enforced
- Obsidian `sensitivity` frontmatter remains a deterministic local privacy gate: `private` is never indexed/exposed, and `sensitive` is excluded while Sensitive is locked
- Vault indexing must decide `sensitivity` from bounded frontmatter pre-scan before any body read; frontmatter is never sent to a model
- Upload intake storage must stay outside the vault, Sensitive vault, and Syncthing-backed `llm-workspace`; uploads only enter the graph after explicit promotion

## Working Rules
- Before editing, state intended scope and likely files touched.
- Keep changes scoped to the requested subsystem.
- Prefer batched, bounded subsystem changes over scattered micro-edits.
- Do not perform broad refactors unless explicitly requested.
- Do not change public API response shapes unless required and verified.
- Do not add dependencies unless justified by the task.
- Preserve deterministic tool execution and policy boundaries.
- Treat Sensitive vault logic as security-sensitive.
- Treat SSE replay, worker/tmux/SSH orchestration, model routing, budget tracking, and cross-host behavior as high-risk areas.
- Never ask Daniel to manually write tests; write and run the smallest relevant checks yourself.
- When committing or pushing from Codex, use neutral commit messages and do not add Codex authorship, co-author, or branding text.
- When Daniel explicitly wants direct pushes, push to `main`; do not create feature branches or PR-oriented workflow unless requested.

## Deployment And Helper Packaging
- Use `scripts/deploy_serrano.sh` for normal serrano deploys. It syncs backend source, syncs the separate frontend service tree, installs helper wrappers, rebuilds the vault index, runs focused privacy/helper checks, builds frontend, and restarts services.
- Production backend service source is `/home/danielju/delamain/backend`; production frontend service source is `/home/danielju/delamain/frontend`.
- `llm-workspace/bin` should contain wrapper scripts only. Helper implementation belongs in repo package `delamain_ref/`.
- After helper behavior changes, install wrappers from `scripts/helper_wrappers/` and rebuild with `/home/danielju/llm-workspace/bin/delamain-vault-index build --json`.
- Upload intake is backend-owned under `delamain_backend/uploads.py` and API-owned under `delamain_backend/api/uploads.py`. Browser uploads are temporary originals plus extracted fallback context; rich prompt attachments pass native file parts through `delamain_backend/agent/litellm_client.py` when supported, and promotion copies into repo-helper-managed workspace bundles.
- If deployment must be manual, keep backend repo sync, frontend service sync, helper wrapper install, vault-index rebuild, frontend build, and backend/frontend restarts as distinct steps.

## Current Development Posture
- The backend foundation is broadly implemented and production-verified; default new work should bias toward frontend UI/UX iteration, accessibility, and operational polish.
- Backend changes are still allowed when needed, but treat them as focused contract accommodations, bug fixes, or policy-safe extensions rather than broad backend construction.
- Keep `AGENTS.md` stable. Put volatile details such as commit IDs, PIDs, deployment transcripts, one-off prompt names, and live verification timelines in `docs/DELAMAIN_AGENT_STATE.md`.

## Tooling And Plugins Guidance
- Prefer Browser Use for in-app browser inspection, screenshots, interaction checks, and UI QA.
- Prefer `webapp-testing` for repeatable Playwright regression work or scripted local browser smoke tests.
- Use the GitHub plugin only for GitHub repository, PR, issue, or CI workflows.
- Use Cloudflare tooling only for Cloudflare configuration, Access/Tunnel, Workers, or platform API work.
- Use Sentry/DataDog skills only when those systems are configured or logs/issues are explicitly requested.
- Avoid Computer Use for browser QA unless Browser Use fails or the target is not accessible through Browser Use.
- Use Build Web Apps skills selectively for frontend design work; preserve DELAMAIN's dense operational interface and avoid landing-page or marketing patterns.

## Verification Rules
- If behavior changes, write or update the smallest relevant regression test or check.
- Run the smallest relevant verification command available.
- If verification cannot be run, explain exactly why.
- Always report commands run and results.
- For frontend work, report any typecheck, build, or browser verification performed.

## Completion Report
Every completed task should end with:
- Files changed
- Summary of changes
- Commands run
- Tests/checks passed or failed
- Known risks
- Recommended next task

## Orchestrator And Task Threads
Preferred operating model for this repo:
- Keep one long-running orchestrator thread for global project understanding.
- Use separate task threads for bounded implementation or investigation.
- Only one writing agent per subsystem/file area at a time.
- Parallel read-only investigation is okay.
- Task threads should read this file plus `docs/DELAMAIN_AGENT_STATE.md` first.
- Task threads should return a concise summary suitable for pasting back into the orchestrator.
- Keep the orchestrator responsible for queue, merge order, doc refresh, and cross-subsystem risk tracking.

If the current Codex session exposes subagent tools such as `spawn_agent`, `send_input`, `wait_agent`, and `close_agent`, the orchestrator may delegate work directly. Use them this way:
- use `spawn_agent` for bounded sidecar tasks only, not for the immediate blocking step
- keep each subagent's write scope disjoint
- have subagents return a compact summary, changed files, commands run, and residual risks
- use `wait_agent` sparingly; do useful local work while subagents run
- close finished agents when they are no longer needed

If the current session does not expose subagent tools, emulate the same workflow with separate Codex app threads under the same project.

Important:
- `AGENTS.md` can instruct an agent to use subagents when available, but it cannot force the Codex app to expose or invoke delegation tools.
- app-level threads and tool-level subagents are related workflow concepts, not the same mechanism.
- In the Codex app, start DELAMAIN work inside the DELAMAIN project that points at `/Users/danielju/Desktop/delamain-assistant.nosync`; threads opened under that project should automatically inherit this `AGENTS.md`.

## Model Guidance
See `docs/agent-model-routing.md` for full routing guidance and prompt templates.

Default recommendations:
- orchestrator: `GPT-5.5` with `high` or `xhigh` thinking for architecture, batching, and risky integration judgment
- normal implementation thread: `gpt-5.4` with `medium`, raise to `high` for ambiguous multi-file work
- review or bulk triage thread: `gpt-5.3-codex` with `medium` or `high`
- fast small follow-up thread: `gpt-5.3-codex-spark` with `low` or `medium`
- docs or low-risk cleanup thread: `gpt-5.4-mini` with `low` or `medium`

Use `GPT-5.5` when a bad answer would waste hours or create subtle policy, orchestration, or security bugs.

## Additional Agent Docs
Read these before substantial work:
- `docs/DELAMAIN_AGENT_STATE.md`
- `docs/agent-model-routing.md`
- `frontend_contract.md`
- `docs/vault-graph-contract.md` - when touching Vault, graph, context preview, pins, policy, or generated relation surfaces
- `README.md` - only if necessary
