#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REMOTE="${DELAMAIN_DEPLOY_HOST:-serrano}"
REMOTE_BACKEND="${DELAMAIN_REMOTE_BACKEND:-/home/danielju/delamain/backend}"
REMOTE_FRONTEND="${DELAMAIN_REMOTE_FRONTEND:-/home/danielju/delamain/frontend}"
REMOTE_WORKSPACE="${DELAMAIN_REMOTE_WORKSPACE:-/home/danielju/llm-workspace}"
BACKEND_PY="${DELAMAIN_REMOTE_BACKEND_PY:-/home/danielju/.local/share/delamain/backend-venv/bin/python}"
LOCAL_HEAD="$(git -C "$ROOT" rev-parse HEAD 2>/dev/null || true)"

log() {
  printf '\n==> %s\n' "$*"
}

log "Sync backend repo to ${REMOTE}:${REMOTE_BACKEND}"
rsync -az --delete \
  --exclude='.git/' \
  --exclude='.venv/' \
  --exclude='.DS_Store' \
  --exclude='__pycache__/' \
  --exclude='.pytest_cache/' \
  --exclude='frontend/node_modules/' \
  --exclude='frontend/.next/' \
  --exclude='frontend/tsconfig.tsbuildinfo' \
  --include='frontend/.env.local.example' \
  --exclude='.env' \
  --exclude='.env.*' \
  "${ROOT}/" "${REMOTE}:${REMOTE_BACKEND}/"

log "Sync frontend service tree to ${REMOTE}:${REMOTE_FRONTEND}"
rsync -az --delete \
  --exclude='node_modules/' \
  --exclude='.next/' \
  --exclude='tsconfig.tsbuildinfo' \
  --include='.env.local.example' \
  --exclude='.env' \
  --exclude='.env.*' \
  "${ROOT}/frontend/" "${REMOTE}:${REMOTE_FRONTEND}/"

log "Install helper wrappers, run focused checks, rebuild vault index, build frontend, restart services"
ssh "$REMOTE" bash -s -- "$REMOTE_BACKEND" "$REMOTE_FRONTEND" "$REMOTE_WORKSPACE" "$BACKEND_PY" "$LOCAL_HEAD" <<'REMOTE_SCRIPT'
set -euo pipefail

REMOTE_BACKEND="$1"
REMOTE_FRONTEND="$2"
REMOTE_WORKSPACE="$3"
BACKEND_PY="$4"
LOCAL_HEAD="$5"
BIN_DIR="${REMOTE_WORKSPACE}/bin"
export REMOTE_WORKSPACE

log() {
  printf '\n==> %s\n' "$*"
}

log "Install thin helper wrappers"
install -m 755 "${REMOTE_BACKEND}/scripts/helper_wrappers/delamain-ref" "${BIN_DIR}/delamain-ref"
install -m 755 "${REMOTE_BACKEND}/scripts/helper_wrappers/delamain-vault-index" "${BIN_DIR}/delamain-vault-index"
if [[ -d "${BIN_DIR}/delamain_ref" ]]; then
  mv "${BIN_DIR}/delamain_ref" "${BIN_DIR}/delamain_ref.legacy-$(date -u +%Y%m%dT%H%M%SZ)"
fi

if [[ -n "$LOCAL_HEAD" && -d "${REMOTE_BACKEND}/.git" ]]; then
  log "Align remote git metadata when pushed commit is available"
  cd "$REMOTE_BACKEND"
  git fetch origin main >/dev/null 2>&1 || true
  if git cat-file -e "${LOCAL_HEAD}^{commit}" 2>/dev/null; then
    git reset --mixed "$LOCAL_HEAD" >/dev/null
  else
    echo "Local commit ${LOCAL_HEAD} is not available in remote git metadata; leaving metadata unchanged." >&2
  fi
fi

log "Backend/helper compile and focused tests"
cd "$REMOTE_BACKEND"
"$BACKEND_PY" -m py_compile \
  delamain_backend/uploads.py \
  delamain_backend/api/uploads.py \
  delamain_backend/security/vault.py \
  delamain_backend/vault_generated.py \
  delamain_backend/api/vault.py \
  delamain_ref/vault_index.py
"$BACKEND_PY" -m pytest -q tests/test_uploads.py tests/test_delamain_ref.py tests/test_vault_api.py -k "frontmatter or sensitivity or upload or native_file"

log "Rebuild vault index through repo-backed wrapper"
"${BIN_DIR}/delamain-vault-index" build --json

log "Verify privacy-sensitive graph artifacts"
python3 - <<'PY'
from __future__ import annotations

import json
import os
from pathlib import Path

idx = Path(os.environ["REMOTE_WORKSPACE"]) / "vault-index"
manifest = json.loads((idx / "_manifest.json").read_text(encoding="utf-8"))
graph = json.loads((idx / "graph.json").read_text(encoding="utf-8"))
checks = {
    "private_sensitive_nodes": 0,
    "frontmatter_skip_records_with_paths": 0,
}
for node in graph.get("nodes", []):
    if str(node.get("sensitivity") or "normal").lower() in {"private", "sensitive"}:
        checks["private_sensitive_nodes"] += 1
for item in manifest.get("skipped_paths", []):
    if (
        isinstance(item, dict)
        and str(item.get("reason") or "").startswith("frontmatter:")
        and item.get("path")
    ):
        checks["frontmatter_skip_records_with_paths"] += 1
payload = {
    "ok": all(value == 0 for value in checks.values()),
    "generated_at": manifest.get("generated_at"),
    "nodes": len(graph.get("nodes", [])),
    "edges": len(graph.get("edges", [])),
    "checks": checks,
}
print(json.dumps(payload, sort_keys=True))
if not payload["ok"]:
    raise SystemExit(1)
PY

log "Install frontend dependencies and build"
cd "$REMOTE_FRONTEND"
corepack pnpm install --frozen-lockfile
timeout 20s systemctl --user stop delamain-frontend.service || true
corepack pnpm build
systemctl --user start delamain-frontend.service

log "Restart backend service"
timeout 20s systemctl --user stop delamain-backend.service || true
sleep 3
if ! systemctl --user is-active --quiet delamain-backend.service \
  && ! systemctl --user is-failed --quiet delamain-backend.service; then
  :
elif systemctl --user show delamain-backend.service -p ActiveState --value | grep -q '^deactivating$'; then
  systemctl --user kill --kill-who=main --signal=SIGKILL delamain-backend.service || true
  sleep 1
fi
systemctl --user reset-failed delamain-backend.service || true
systemctl --user start delamain-backend.service

for _ in {1..30}; do
  backend_http="$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8420/api/health || true)"
  if [[ "$backend_http" != "000" ]]; then
    break
  fi
  sleep 1
done

log "Service and HTTP checks"
systemctl --user is-active delamain-frontend.service
systemctl --user is-active delamain-backend.service
printf 'frontend_http='
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:3000/
printf 'backend_http='
backend_http="$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8420/api/health || true)"
printf '%s\n' "$backend_http"
if [[ "$backend_http" == "000" ]]; then
  echo "Backend did not respond on 127.0.0.1:8420." >&2
  exit 1
fi

log "Remote git status"
cd "$REMOTE_BACKEND"
git rev-parse HEAD
git status --short
REMOTE_SCRIPT

log "Deploy complete"
