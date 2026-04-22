from __future__ import annotations

from pathlib import Path
import os

import pytest

from delamain_backend.config import (
    AppConfig,
    DatabaseConfig,
    ModelsConfig,
    PathsConfig,
    RuntimeConfig,
    ServerConfig,
    ToolsConfig,
)


@pytest.fixture
def test_config(tmp_path: Path) -> AppConfig:
    workspace = tmp_path / "llm-workspace"
    (workspace / "context" / "short-term").mkdir(parents=True)
    (workspace / "context" / "system-context.md").write_text("system", encoding="utf-8")
    (workspace / "context" / "short-term" / "continuity.md").write_text(
        "continuity", encoding="utf-8"
    )
    bin_dir = workspace / "bin"
    bin_dir.mkdir()
    _write_executable(bin_dir / "now", "#!/usr/bin/env bash\nprintf '2026-04-17 Friday 12:00:00 EDT\\n'\n")
    _write_executable(
        bin_dir / "delamain-ref",
        "#!/usr/bin/env bash\nprintf '{\"ok\":true,\"status\":\"ready\",\"tool\":\"delamain-ref\"}\\n'\n",
    )
    _write_executable(
        bin_dir / "delamain-vault-index",
        "#!/usr/bin/env bash\nprintf '{\"ok\":true,\"status\":\"ready\",\"tool\":\"delamain-vault-index\"}\\n'\n",
    )
    return AppConfig(
        server=ServerConfig(host="127.0.0.1", port=8420),
        database=DatabaseConfig(path=tmp_path / "conversations.sqlite"),
        paths=PathsConfig(
            vault=tmp_path / "Vault",
            sensitive=tmp_path / "Sensitive",
            llm_workspace=workspace,
        ),
        models=ModelsConfig(
            default="github_copilot/gpt-5.4-mini",
            fallback_high_volume="github_copilot/gpt-5-mini",
            fallback_cheap="github_copilot/claude-haiku-4.5",
            paid_fallback="openrouter/deepseek/deepseek-v3.2",
        ),
        tools=ToolsConfig(
            max_tool_iterations=8,
            default_timeout_seconds=2,
            output_limit_bytes=200000,
        ),
        runtime=RuntimeConfig(
            enable_model_calls=False,
            disable_model_fallbacks=False,
            model_timeout_seconds=30,
        ),
    )


def _write_executable(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    os.chmod(path, 0o755)
