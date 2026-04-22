from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from delamain_backend.config import AppConfig


@dataclass(frozen=True)
class WorkerType:
    id: str
    label: str
    description: str
    command_template: tuple[str, ...]
    host: str = "serrano"
    cwd: Path | None = None
    env_extras: dict[str, str] = field(default_factory=dict)

    def public_dict(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "description": self.description,
            "command_template": list(self.command_template),
            "host": self.host,
        }


class WorkerTypeRegistry:
    def __init__(self, types: list[WorkerType]):
        self._types = {wt.id: wt for wt in types}

    def list(self) -> list[dict]:
        return [self._types[wt_id].public_dict() for wt_id in sorted(self._types)]

    def get(self, worker_type_id: str) -> WorkerType | None:
        return self._types.get(worker_type_id)

    def type_ids(self) -> list[str]:
        return sorted(self._types)


def default_worker_registry(config: AppConfig) -> WorkerTypeRegistry:
    return WorkerTypeRegistry(
        [
            WorkerType(
                id="opencode",
                label="OpenCode",
                description="Start an OpenCode agent session on serrano.",
                command_template=(
                    "/home/danielju/.local/bin/opencode",
                ),
                host="serrano",
                cwd=Path("/home/danielju/Vault"),
            ),
            WorkerType(
                id="claude_code",
                label="Claude Code",
                description="Start a Claude Code agent session on serrano.",
                command_template=(
                    "claude",
                ),
                host="serrano",
                cwd=Path("/home/danielju"),
            ),
            WorkerType(
                id="shell",
                label="Shell",
                description="Start a plain bash shell session on serrano.",
                command_template=(
                    "/bin/bash", "--login",
                ),
                host="serrano",
                cwd=Path("/home/danielju"),
            ),
            WorkerType(
                id="winpc_shell",
                label="WinPC Shell",
                description="Start a plain bash shell session in WSL tmux on winpc.",
                command_template=(
                    "/bin/bash", "--login",
                ),
                host="winpc",
                cwd=Path("/home/daniel"),
            ),
        ]
    )
