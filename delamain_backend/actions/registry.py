from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from delamain_backend.config import AppConfig


@dataclass(frozen=True)
class ActionSpec:
    id: str
    label: str
    description: str
    argv: tuple[str, ...]
    cwd: Path
    timeout_seconds: float
    writes: bool = False
    remote: bool = False
    approval_policy_default: str = "auto"
    risk: str = "low"

    def public_dict(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "description": self.description,
            "argv": list(self.argv),
            "cwd": str(self.cwd),
            "timeout_seconds": self.timeout_seconds,
            "writes": self.writes,
            "remote": self.remote,
            "approval_policy_default": self.approval_policy_default,
            "risk": self.risk,
        }


class ActionRegistry:
    def __init__(self, specs: list[ActionSpec]):
        self._specs = {spec.id: spec for spec in specs}

    def list(self) -> list[dict]:
        return [self._specs[action_id].public_dict() for action_id in sorted(self._specs)]

    def get(self, action_id: str) -> ActionSpec | None:
        return self._specs.get(action_id)


def default_action_registry(config: AppConfig) -> ActionRegistry:
    workspace_bin = config.paths.llm_workspace / "bin"
    backend_root = Path(__file__).resolve().parents[2]
    python = "/usr/bin/python3"
    ssh = "/usr/bin/ssh"
    helper_check = (
        "import json, os, sys; "
        "print(json.dumps({os.path.basename(p): {'path': p, 'exists': os.path.exists(p), "
        "'executable': os.access(p, os.X_OK)} for p in sys.argv[1:]}, sort_keys=True))"
    )
    return ActionRegistry(
        [
            ActionSpec(
                id="health.backend",
                label="Backend health",
                description="Check whether the DELAMAIN backend user service is active.",
                argv=(
                    "/usr/bin/systemctl",
                    "--user",
                    "is-active",
                    "delamain-backend.service",
                ),
                cwd=backend_root,
                timeout_seconds=5,
            ),
            ActionSpec(
                id="health.helpers",
                label="Helper health",
                description="Check presence and executability for deterministic helper commands.",
                argv=(
                    python,
                    "-c",
                    helper_check,
                    str(workspace_bin / "now"),
                    str(workspace_bin / "delamain-ref"),
                    str(workspace_bin / "delamain-vault-index"),
                ),
                cwd=config.paths.llm_workspace,
                timeout_seconds=5,
            ),
            ActionSpec(
                id="ref.status",
                label="Reference status",
                description="Run delamain-ref status.",
                argv=(str(workspace_bin / "delamain-ref"), "status", "--json"),
                cwd=config.paths.llm_workspace,
                timeout_seconds=15,
            ),
            ActionSpec(
                id="ref.reconcile_dry_run",
                label="Reference reconcile dry run",
                description="Preview reference reconciliation without moving files.",
                argv=(
                    str(workspace_bin / "delamain-ref"),
                    "reconcile",
                    "--dry-run",
                    "--json",
                ),
                cwd=config.paths.llm_workspace,
                timeout_seconds=30,
            ),
            ActionSpec(
                id="vault_index.status",
                label="Vault index status",
                description="Run delamain-vault-index status.",
                argv=(str(workspace_bin / "delamain-vault-index"), "status", "--json"),
                cwd=config.paths.llm_workspace,
                timeout_seconds=15,
            ),
            ActionSpec(
                id="vault_index.build",
                label="Build vault index",
                description="Rebuild the deterministic vault index.",
                argv=(str(workspace_bin / "delamain-vault-index"), "build", "--json"),
                cwd=config.paths.llm_workspace,
                timeout_seconds=30,
                writes=True,
                risk="write",
            ),
            ActionSpec(
                id="vault_index.init_project",
                label="New project folder",
                description="Create a templated DELAMAIN project folder and rebuild the unified graph.",
                argv=(
                    str(workspace_bin / "delamain-vault-index"),
                    "init-folder",
                    "--kind",
                    "project",
                    "--name",
                    "New Project",
                    "--json",
                ),
                cwd=config.paths.llm_workspace,
                timeout_seconds=30,
                writes=True,
                risk="write",
            ),
            ActionSpec(
                id="vault_index.init_course",
                label="New course folder",
                description="Create a templated DELAMAIN course folder and rebuild the unified graph.",
                argv=(
                    str(workspace_bin / "delamain-vault-index"),
                    "init-folder",
                    "--kind",
                    "course",
                    "--name",
                    "New Course",
                    "--json",
                ),
                cwd=config.paths.llm_workspace,
                timeout_seconds=30,
                writes=True,
                risk="write",
            ),
            ActionSpec(
                id="vault_index.init_reference",
                label="New reference folder",
                description="Create a templated DELAMAIN reference folder and rebuild the unified graph.",
                argv=(
                    str(workspace_bin / "delamain-vault-index"),
                    "init-folder",
                    "--kind",
                    "reference",
                    "--name",
                    "New Reference",
                    "--json",
                ),
                cwd=config.paths.llm_workspace,
                timeout_seconds=30,
                writes=True,
                risk="write",
            ),
            ActionSpec(
                id="sync_guard.status",
                label="Sync guard status",
                description="Run the Syncthing sync guard health check.",
                argv=(python, str(workspace_bin / "sync_guard.py"), "health"),
                cwd=config.paths.llm_workspace,
                timeout_seconds=20,
            ),
            ActionSpec(
                id="subscription.codex_status",
                label="Codex subscription status",
                description="Check local Codex CLI login/subscription readiness.",
                argv=("/bin/bash", "--login", "-lc", "codex --version && codex login status"),
                cwd=backend_root,
                timeout_seconds=8,
            ),
            ActionSpec(
                id="subscription.claude_status",
                label="Claude Code subscription status",
                description="Check local Claude Code auth and subscription readiness.",
                argv=("/bin/bash", "--login", "-lc", "claude --version && claude auth status"),
                cwd=backend_root,
                timeout_seconds=8,
            ),
            ActionSpec(
                id="subscription.gemini_status",
                label="Gemini CLI status",
                description="Check local Gemini CLI installation/auth readiness.",
                argv=("/bin/bash", "--login", "-lc", "gemini --version"),
                cwd=backend_root,
                timeout_seconds=8,
            ),
            ActionSpec(
                id="winpc.subscription_codex_status",
                label="WinPC Codex subscription status",
                description="Check Codex CLI login/subscription readiness in WinPC WSL.",
                argv=(
                    ssh,
                    "winpc",
                    'wsl.exe -e bash --login -lc "codex --version && codex login status"',
                ),
                cwd=config.paths.llm_workspace,
                timeout_seconds=12,
                remote=True,
            ),
            ActionSpec(
                id="winpc.subscription_claude_status",
                label="WinPC Claude Code subscription status",
                description="Check Claude Code auth and subscription readiness in WinPC WSL.",
                argv=(
                    ssh,
                    "winpc",
                    'wsl.exe -e bash --login -lc "claude --version && claude auth status"',
                ),
                cwd=config.paths.llm_workspace,
                timeout_seconds=12,
                remote=True,
            ),
            ActionSpec(
                id="winpc.hostname",
                label="WinPC hostname",
                description="Check the Windows host name over SSH.",
                argv=(ssh, "winpc", "hostname"),
                cwd=config.paths.llm_workspace,
                timeout_seconds=10,
                remote=True,
            ),
            ActionSpec(
                id="winpc.date",
                label="WinPC date",
                description="Check the Windows host date over SSH.",
                argv=(
                    ssh,
                    "winpc",
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    "Get-Date -Format o",
                ),
                cwd=config.paths.llm_workspace,
                timeout_seconds=10,
                remote=True,
            ),
        ]
    )
