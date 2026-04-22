from dataclasses import replace

import pytest

from delamain_backend.config import PathsConfig
from delamain_backend.errors import SensitiveLocked, ToolPolicyDenied
from delamain_backend.security import PathPolicy


@pytest.fixture
def m4_config(test_config, tmp_path):
    vault = tmp_path / "Vault"
    workspace = tmp_path / "llm-workspace"
    sensitive = tmp_path / "Sensitive"
    vault.mkdir(exist_ok=True)
    workspace.mkdir(exist_ok=True)
    sensitive.mkdir(exist_ok=True)
    return replace(
        test_config,
        paths=PathsConfig(vault=vault, sensitive=sensitive, llm_workspace=workspace),
    )


def test_path_policy_allows_normal_roots(m4_config):
    note = m4_config.paths.vault / "note.md"
    note.write_text("hello", encoding="utf-8")
    decision = PathPolicy(m4_config).check(
        str(note),
        operation="read",
        sensitive_unlocked=False,
    )
    assert decision.root_name == "vault"
    assert decision.sensitive is False


def test_path_policy_blocks_outside_roots(m4_config, tmp_path):
    outside = tmp_path / "outside.md"
    outside.write_text("no", encoding="utf-8")
    with pytest.raises(ToolPolicyDenied):
        PathPolicy(m4_config).check(
            str(outside),
            operation="read",
            sensitive_unlocked=False,
        )


def test_path_policy_blocks_sensitive_when_locked(m4_config):
    secret = m4_config.paths.sensitive / "harmless.md"
    secret.write_text("test fixture only", encoding="utf-8")
    with pytest.raises(SensitiveLocked):
        PathPolicy(m4_config).check(
            str(secret),
            operation="read",
            sensitive_unlocked=False,
        )


def test_path_policy_allows_sensitive_when_unlocked(m4_config):
    secret = m4_config.paths.sensitive / "harmless.md"
    secret.write_text("test fixture only", encoding="utf-8")
    decision = PathPolicy(m4_config).check(
        str(secret),
        operation="read",
        sensitive_unlocked=True,
    )
    assert decision.root_name == "sensitive"
    assert decision.sensitive is True


@pytest.mark.parametrize("name", [".env", "id_ed25519", "token-store.txt", "archive.pdf"])
def test_path_policy_blocks_restricted_patterns(m4_config, name):
    blocked = m4_config.paths.vault / name
    blocked.write_text("blocked", encoding="utf-8")
    with pytest.raises(ToolPolicyDenied):
        PathPolicy(m4_config).check(
            str(blocked),
            operation="read",
            sensitive_unlocked=False,
        )
