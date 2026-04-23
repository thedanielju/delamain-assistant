# DELAMAIN

DELAMAIN is Daniel Ju's personal browser-based LLM assistant. It combines a FastAPI backend, a Next.js chat frontend, deterministic local tools, vault-aware context handling, guarded Sensitive access, usage and subscription visibility, Syncthing status, and tmux-backed worker sessions across `serrano` and `winpc`.

This repository contains the Phase 2 application code for both the backend and the frontend.

The detailed operational source of truth lives in Daniel's Obsidian vault under `Projects/DELAMAIN/`. This README is the repo-local overview and tutorial.

## Contents

- [What DELAMAIN Is](#what-delamain-is)
- [What This Repository Contains](#what-this-repository-contains)
- [Current Status](#current-status)
- [Architecture](#architecture)
- [Key Features](#key-features)
- [Repository Layout](#repository-layout)
- [Using DELAMAIN](#using-delamain)
- [Local Development](#local-development)
- [Deployment on Serrano](#deployment-on-serrano)
- [Security Model](#security-model)
- [Testing](#testing)
- [Important Documents](#important-documents)

## What DELAMAIN Is

DELAMAIN is not a generic chatbot product. It is a personal assistant system designed around Daniel's actual working environment:

- an Obsidian-based knowledge base
- a synced `llm-workspace`
- a separate Sensitive vault
- deterministic helper tools for references, indexing, and sync health
- a persistent Linux host on `serrano`
- a Windows machine on `winpc`

The goal is a practical assistant that can:

- hold long-running conversations
- stream responses in the browser
- safely inspect Daniel's vault and workspace
- expose deterministic quick actions for operational checks
- show usage and subscription status for the model providers Daniel actually uses
- coordinate worker sessions on `serrano` and `winpc`
- keep a strict boundary around Sensitive data

## What This Repository Contains

This repository includes:

1. `delamain_backend/`
   - the FastAPI backend
   - routing, persistence, SSE, settings, permissions, tool policy, Syncthing, usage, workers, and auth

2. `frontend/`
   - the Next.js frontend
   - conversation UI, settings UI, health and usage panels, Syncthing panel, workers panel, context editor, and direct actions

3. `tests/`
   - backend regression and contract tests

4. `frontend_contract.md`
   - the repo-local copy of the current frontend/backend API contract

## Current Status

As of 2026-04-23:

- the backend contract described for Phase 2 is implemented in this repo
- the frontend is wired against that contract
- the production backend on `serrano` runs on `127.0.0.1:8420`
- a dev-local backend sidecar runs on `127.0.0.1:8421`
- the `serrano` frontend service runs on `127.0.0.1:3000`
- `chat.danielju.com` serves the Next.js frontend
- `term.danielju.com` remains the Cloudflare Access protected admin and ttyd surface

Important deployment note:

- the public frontend currently rewrites same-origin `/api/*` to the dev-local backend sidecar on `8421`
- the hardened production backend with Cloudflare Access enforcement remains on `8420`

So the code is in place, but the final public ingress path is still in a transitional state.

## Architecture

### Backend

The backend is a FastAPI app with:

- SQLite persistence
- background run processing
- SSE replay and live streaming
- LiteLLM model routing
- tool-call persistence
- deterministic quick actions
- context file read and guarded write support
- per-tool approval policies
- permission request and resolve flows
- usage, subscription, and Syncthing reporting
- worker session lifecycle management

### Frontend

The frontend is a Next.js application that provides:

- conversation list and nested folders
- streamed chat UI
- run controls
- tool and permission surfaces
- settings and model route controls
- health, usage, Syncthing, and workers panels
- direct action shortcuts
- context editing for the supported context files

### Storage and Runtime Data

The application code lives in this repository, but runtime state is intentionally kept outside Syncthing on `serrano`.

Important runtime locations:

- backend database:
  - `/home/danielju/.local/share/delamain/conversations.sqlite`
- backend action artifacts:
  - `/home/danielju/.local/share/delamain/action-outputs/`
- context backups:
  - `/home/danielju/.local/share/delamain/context-backups/`

### Machines

- `serrano`
  - primary Linux host
  - backend service
  - frontend service
  - ttyd
  - tmux workers

- `winpc`
  - Windows-side helper host
  - WSL worker target
  - remote shell target for specific quick actions and worker types

## Key Features

### Conversations and Runs

- create, update, archive, move, and delete conversations
- nested folders with cycle prevention
- queue and background execution for runs
- SSE streaming with replay support via `Last-Event-ID`
- cancel and retry controls

### Vault and Context Handling

- normal and blank-slate context modes
- current context inspection
- editable `system-context`
- editable `short-term-continuity`
- backend-enforced path policy for vault and workspace access

### Sensitive Access

- Sensitive is locked by default per conversation
- unlock and lock are explicit REST actions
- Sensitive access attempts are audited
- the model does not get an unlock tool

### Deterministic Quick Actions

Examples include:

- backend health
- helper health
- reference status
- vault index status and build
- sync guard status
- subscription status for Codex, Claude Code, and Gemini
- WinPC hostname and date

### Usage and Subscription Visibility

- Copilot budget reporting
- usage provider summaries
- subscription and auth probes for Codex, Claude Code, and Gemini

### Syncthing Visibility

- summary by device
- conflict listing
- conflict resolution endpoints
- expected device rows including local and iPhone probe-only presence

### Workers

- `serrano` shell workers
- `winpc` WSL worker sessions
- capture, stop, and kill operations
- persistent metadata and startup reconciliation

## Repository Layout

```text
.
├── config/
│   └── defaults.yaml
├── delamain_backend/
│   ├── actions/
│   ├── agent/
│   ├── api/
│   ├── db/
│   ├── events/
│   ├── security/
│   ├── tools/
│   └── workers/
├── frontend/
│   ├── app/
│   ├── components/
│   ├── hooks/
│   ├── lib/
│   └── public/
├── scripts/
├── tests/
├── frontend_contract.md
├── pyproject.toml
└── README.md
```

## Using DELAMAIN

### For Daniel as a User

Typical flow:

1. Open the browser UI.
2. Select or create a conversation.
3. Pick a folder if organization matters.
4. Send a prompt.
5. Watch the streamed response and any tool cards.
6. Use the right-hand panels for health, usage, Syncthing, workers, or settings.
7. Use direct actions for deterministic checks that should not go through the model.
8. Unlock Sensitive only when a conversation truly needs it.

### For UI Refinement

The fastest feedback loop is the local Mac wrapper:

- URL:
  - `http://127.0.0.1:3000`
- behavior:
  - real frontend
  - real API data
  - proxied to the `serrano` dev-local backend sidecar

That setup is for iteration speed. It is not the final production auth path.

## Local Development

### Prerequisites

- Python 3.12+
- Node.js 20+
- `pnpm` via `corepack`

### 1. Clone the repository

```bash
git clone https://github.com/thedanielju/delamain-assistant.git
cd delamain-assistant
```

### 2. Set up the backend

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e .[test]
```

### 3. Run the backend locally

Use `dev_local` auth for local work:

```bash
export DELAMAIN_AUTH_MODE=dev_local
uvicorn delamain_backend.main:app --reload --host 127.0.0.1 --port 8420
```

Optional overrides:

```bash
export DELAMAIN_DB_PATH=/tmp/delamain.sqlite
export DELAMAIN_ENABLE_MODEL_CALLS=0
```

### 4. Set up the frontend

```bash
cd frontend
corepack enable
pnpm install
```

### 5. Run the frontend against the local backend

The frontend is designed to use same-origin `/api`, so local development should use the built-in rewrite:

```bash
export NEXT_PUBLIC_DELAMAIN_MOCK=0
export NEXT_PUBLIC_DELAMAIN_API_BASE=/api
export DELAMAIN_DEV_API_PROXY=http://127.0.0.1:8420
pnpm dev
```

Then open:

```text
http://127.0.0.1:3000
```

### 6. Run the frontend against `serrano`

If you want the UI to talk to the `serrano` dev-local sidecar instead of a local backend:

```bash
export NEXT_PUBLIC_DELAMAIN_MOCK=0
export NEXT_PUBLIC_DELAMAIN_API_BASE=/api
export DELAMAIN_DEV_API_PROXY=http://127.0.0.1:18421
pnpm dev
```

This assumes you already have a local tunnel forwarding `127.0.0.1:18421` to `serrano:8421`.

## Deployment on Serrano

### Backend service

The backend is managed as a user service:

```bash
systemctl --user status delamain-backend.service --no-pager
systemctl --user restart delamain-backend.service
journalctl --user -u delamain-backend.service -n 100 --no-pager
```

Service unit:

```text
/home/danielju/.config/systemd/user/delamain-backend.service
```

### Frontend service

The frontend is also managed as a user service:

```bash
systemctl --user status delamain-frontend.service --no-pager
systemctl --user restart delamain-frontend.service
journalctl --user -u delamain-frontend.service -n 100 --no-pager
```

Service unit:

```text
/home/danielju/.config/systemd/user/delamain-frontend.service
```

At the moment that service is configured with:

- `NEXT_PUBLIC_DELAMAIN_API_BASE=/api`
- `DELAMAIN_DEV_API_PROXY=http://127.0.0.1:8421`
- port `3000`

That is why the public frontend is still using the transitional API path.

### Open WebUI status

Open WebUI is no longer the live service on port `3000`.

Operational changes already made on `serrano`:

- `open-webui` container stopped
- restart policy set to `no`
- `watchtower` container stopped
- restart policy set to `no`

### Public surfaces

- `chat.danielju.com`
  - Next.js frontend on `serrano`
  - currently using the transitional `/api -> 8421` path

- `term.danielju.com`
  - Cloudflare Access protected admin and ttyd surface
  - `/api` forwarded to production backend on `8420`
  - `/` forwarded to ttyd

## Security Model

### Auth

- production backend auth is based on Cloudflare Access JWT validation
- local development uses `DELAMAIN_AUTH_MODE=dev_local`
- clients should treat auth failures as origin-level stale auth, not as a separate app login

### Filesystem Access

Allowed roots:

- vault
- `llm-workspace`
- Sensitive

Sensitive rules:

- locked by default
- unlocked per conversation only
- no model-side unlock capability
- access attempts audited

### Write Tools

Write access is intentionally narrow:

- guarded `patch_text_file`
- guarded `run_shell`
- no broad arbitrary file creation or overwrite tools

## Testing

### Backend tests

From the repo root:

```bash
pytest -q
```

### Frontend checks

From `frontend/`:

```bash
pnpm tsc --noEmit
pnpm build
```

### Live smoke

There is also a guarded live smoke script:

```bash
python scripts/live_model_smoke.py
```

It refuses to run unless live model calls are explicitly enabled.

## Important Documents

- repo-local frontend/backend API contract:
  - [frontend_contract.md](./frontend_contract.md)
- authoritative project notes in the Obsidian vault:
  - `Projects/DELAMAIN/DELAMAIN.md`
  - `Projects/DELAMAIN/state/current-state.md`
  - `Projects/DELAMAIN/state/frontend-contract.md`
  - `Projects/DELAMAIN/state/open_backend_issues.md`
  - `Projects/DELAMAIN/logs/changelog.md`

## Summary

DELAMAIN is a real personal assistant system, not just a prompt wrapper. This repo now holds both halves of the Phase 2 application:

- the backend that owns conversations, policy, state, and machine coordination
- the frontend that exposes those capabilities as a browser interface

If you are editing UI, work from the Mac wrapper first. If you are validating deployment behavior, check the `serrano` services and public hosts. If you are trying to understand the project in full, read the vault notes alongside this README.
