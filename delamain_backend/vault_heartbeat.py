from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from delamain_backend.config import AppConfig
from delamain_backend.db import Database

HEARTBEAT_CADENCE_SECONDS = 300
INACTIVITY_SECONDS = 90


@dataclass
class VaultHeartbeatState:
    signature: str | None = None
    first_seen_at: datetime | None = None
    running: bool = False


class VaultIndexHeartbeat:
    def __init__(
        self,
        config: AppConfig,
        *,
        cadence_seconds: int = HEARTBEAT_CADENCE_SECONDS,
        inactivity_seconds: int = INACTIVITY_SECONDS,
        db: Database | None = None,
    ):
        self.config = config
        self.cadence_seconds = cadence_seconds
        self.inactivity_seconds = inactivity_seconds
        self.db = db
        self.state = VaultHeartbeatState()
        self.status_path = config.paths.llm_workspace / "vault-index" / "_heartbeat.json"

    async def run_forever(self) -> None:
        try:
            while True:
                await asyncio.sleep(self.cadence_seconds)
                await self.run_once()
        except asyncio.CancelledError:
            raise

    async def run_once(self) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        signature = self._source_signature()
        if signature == self.state.signature and self.state.first_seen_at is not None:
            if now - self.state.first_seen_at < timedelta(seconds=self.inactivity_seconds):
                return self._write_status(
                    {
                        "ok": True,
                        "status": "deferred",
                        "reason": "waiting_for_inactivity",
                        "source_signature": signature,
                        "next_run_after": (self.state.first_seen_at + timedelta(seconds=self.inactivity_seconds)).isoformat(),
                    }
                )
            if self.state.running:
                return self._write_status(
                    {
                        "ok": True,
                        "status": "skipped",
                        "reason": "heartbeat_already_running",
                        "source_signature": signature,
                    }
                )
            return await self._run_helper(signature)

        self.state.signature = signature
        self.state.first_seen_at = now
        return self._write_status(
            {
                "ok": True,
                "status": "observed",
                "reason": "change_detected_waiting_for_inactivity",
                "source_signature": signature,
                "next_run_after": (now + timedelta(seconds=self.inactivity_seconds)).isoformat(),
            }
        )

    async def _run_helper(self, signature: str) -> dict[str, Any]:
        self.state.running = True
        started = datetime.now(timezone.utc)
        helper = self.config.paths.llm_workspace / "bin" / "delamain-vault-index"
        try:
            process = await asyncio.create_subprocess_exec(
                str(helper),
                "heartbeat",
                "--json",
                cwd=str(self.config.paths.llm_workspace),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=120)
            payload = _decode_json(stdout)
            status = "ok" if process.returncode == 0 and payload.get("ok", False) else "error"
            result = {
                "ok": status == "ok",
                "status": status,
                "source_signature": signature,
                "started_at": started.isoformat(),
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "exit_code": process.returncode,
                "stdout": payload,
                "stderr_preview": stderr.decode("utf-8", errors="replace")[:2000],
            }
        except Exception as exc:
            result = {
                "ok": False,
                "status": "error",
                "source_signature": signature,
                "started_at": started.isoformat(),
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "error": f"{type(exc).__name__}: {exc}",
            }
        finally:
            self.state.running = False
            self.state.first_seen_at = datetime.now(timezone.utc)
        await self._record_maintenance_proposals(result)
        return self._write_status(result)

    def _source_signature(self) -> str:
        digest = hashlib.sha256()
        roots = [
            self.config.paths.vault,
            self.config.paths.llm_workspace / "syllabi",
            self.config.paths.llm_workspace / "reference",
        ]
        policy_files = [
            self.config.paths.vault / "vault_policy.md",
            self.config.paths.vault / ".modelignore",
            self.config.paths.vault / ".delamainignore",
        ]
        for path in [*policy_files, *self._iter_source_files(roots)]:
            try:
                stat = path.stat()
            except OSError:
                continue
            digest.update(str(path).encode("utf-8"))
            digest.update(str(stat.st_mtime_ns).encode("ascii"))
            digest.update(str(stat.st_size).encode("ascii"))
        return digest.hexdigest()

    def _iter_source_files(self, roots: list[Path]) -> list[Path]:
        files: list[Path] = []
        for root in roots:
            if not root.exists():
                continue
            for path in root.rglob("*"):
                if not path.is_file():
                    continue
                if path.name.startswith("."):
                    continue
                if ".sync-conflict-" in path.name:
                    files.append(path)
                    continue
                if path.suffix.lower() in {".md", ".json", ".pdf", ".docx", ".rtf", ".odt"}:
                    files.append(path)
        return sorted(files, key=lambda item: item.as_posix().lower())

    def _write_status(self, payload: dict[str, Any]) -> dict[str, Any]:
        status = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "cadence_seconds": self.cadence_seconds,
            "inactivity_seconds": self.inactivity_seconds,
            **payload,
        }
        self.status_path.parent.mkdir(parents=True, exist_ok=True)
        self.status_path.write_text(json.dumps(status, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return status

    async def _record_maintenance_proposals(self, result: dict[str, Any]) -> None:
        if self.db is None:
            return
        for proposal in _proposals_from_heartbeat_result(result):
            existing = await self.db.fetchone(
                """
                SELECT id FROM vault_maintenance_proposals
                WHERE kind = ?
                  AND title = ?
                  AND description = ?
                  AND status = 'proposed'
                """,
                (proposal["kind"], proposal["title"], proposal["description"]),
            )
            if existing is not None:
                continue
            await self.db.execute(
                """
                INSERT INTO vault_maintenance_proposals(
                    id, conversation_id, kind, title, description, paths_json, payload_json, status
                )
                VALUES (?, NULL, ?, ?, ?, ?, ?, 'proposed')
                """,
                (
                    f"vmp_{uuid.uuid4().hex[:16]}",
                    proposal["kind"],
                    proposal["title"],
                    proposal["description"],
                    json.dumps(proposal["paths"], sort_keys=True),
                    json.dumps(proposal["payload"], sort_keys=True),
                ),
            )


def _decode_json(data: bytes) -> dict[str, Any]:
    try:
        parsed = json.loads(data.decode("utf-8"))
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _proposals_from_heartbeat_result(result: dict[str, Any]) -> list[dict[str, Any]]:
    source_signature = result.get("source_signature")
    stdout = result.get("stdout") if isinstance(result.get("stdout"), dict) else {}
    proposals: list[dict[str, Any]] = []

    if result.get("status") == "error":
        message = _message_text(result.get("error") or result.get("stderr_preview"))
        if not message:
            message = "Vault index heartbeat failed."
        proposals.append(
            _maintenance_payload(
                kind="vault_index_heartbeat_error",
                severity="error",
                message=message,
                source_signature=source_signature,
            )
        )

    for message in _iter_messages(stdout.get("errors")):
        proposals.append(
            _maintenance_payload(
                kind="workspace_ingest_error",
                severity="error",
                message=message,
                source_signature=source_signature,
            )
        )
    for message in _iter_messages(stdout.get("warnings")):
        proposals.append(
            _maintenance_payload(
                kind="workspace_ingest_warning",
                severity="warning",
                message=message,
                source_signature=source_signature,
            )
        )

    summary = stdout.get("summary") if isinstance(stdout.get("summary"), dict) else {}
    auto_ingest = summary.get("auto_ingest") if isinstance(summary.get("auto_ingest"), dict) else {}
    for message in _iter_messages(auto_ingest.get("errors")):
        proposals.append(
            _maintenance_payload(
                kind="workspace_ingest_error",
                severity="error",
                message=message,
                source_signature=source_signature,
            )
        )
    for message in _iter_messages(auto_ingest.get("warnings")):
        proposals.append(
            _maintenance_payload(
                kind="workspace_ingest_warning",
                severity="warning",
                message=message,
                source_signature=source_signature,
            )
        )
    return proposals


def _iter_messages(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, list):
        messages: list[str] = []
        for item in value:
            text = _message_text(item)
            if text:
                messages.append(text)
        return messages
    text = _message_text(value)
    return [text] if text else []


def _message_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, dict):
        for key in ("message", "error", "warning", "detail", "path"):
            raw = value.get(key)
            if isinstance(raw, str) and raw.strip():
                return raw.strip()
        return json.dumps(value, sort_keys=True)
    return str(value).strip() or None


def _maintenance_payload(
    *,
    kind: str,
    severity: str,
    message: str,
    source_signature: Any,
) -> dict[str, Any]:
    return {
        "kind": kind,
        "title": "Review vault index heartbeat issue",
        "description": message,
        "paths": [],
        "payload": {
            "source": "vault_index_heartbeat",
            "severity": severity,
            "message": message,
            "source_signature": source_signature,
        },
    }
