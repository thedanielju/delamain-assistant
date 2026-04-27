from __future__ import annotations

import os
import platform
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class RuntimePaths:
    workspace_root: Path
    vault_root: Path
    syllabi_root: Path
    reference_root: Path
    transfer_root: Path
    vault_index_root: Path
    skeleton_root: Path

    def category_root(self, category: str) -> Path:
        normalized = category.strip().lower()
        if normalized == "syllabi":
            return self.syllabi_root
        if normalized == "reference":
            return self.reference_root
        raise ValueError(f"Unsupported category: {category}")


def _iter_workspace_candidates() -> list[Path]:
    candidates: list[Path] = []
    env_override = os.environ.get("DELAMAIN_LLM_WORKSPACE")
    if env_override:
        candidates.append(Path(env_override))

    candidates.extend(
        [
            Path(r"C:\Users\Daniel\llm-workspace"),
            Path("/mnt/c/Users/Daniel/llm-workspace"),
            Path("/home/danielju/llm-workspace"),
            Path("/Users/danielju/Desktop/llm-workspace.nosync"),
        ]
    )

    cwd = Path.cwd().resolve()
    for probe in [cwd, *cwd.parents]:
        if probe.name.lower() == "llm-workspace":
            candidates.append(probe)
        nested = probe / "llm-workspace"
        candidates.append(nested)

    return _dedupe_paths(candidates)


def _iter_vault_candidates(workspace_root: Path) -> list[Path]:
    candidates: list[Path] = []
    env_override = os.environ.get("DELAMAIN_VAULT_ROOT")
    if env_override:
        candidates.append(Path(env_override))

    candidates.extend(
        [
            Path(r"C:\Users\Daniel\Desktop\Obsidian\Vault"),
            Path("/mnt/c/Users/Daniel/Desktop/Obsidian/Vault"),
            Path("/home/danielju/Vault"),
            Path("/Users/danielju/Desktop/Obsidian.nosync/Vault"),
        ]
    )

    # Nearby fallback when paths drift with sync relocation.
    if workspace_root.parent.exists():
        candidates.append(workspace_root.parent / "Desktop" / "Obsidian" / "Vault")
    return _dedupe_paths(candidates)


def _dedupe_paths(paths: Iterable[Path]) -> list[Path]:
    seen: set[str] = set()
    ordered: list[Path] = []
    for path in paths:
        key = str(path).lower()
        if key in seen:
            continue
        seen.add(key)
        ordered.append(path)
    return ordered


def discover_workspace_root(explicit_root: str | Path | None = None) -> Path:
    if explicit_root:
        candidate = Path(explicit_root).expanduser().resolve()
        if candidate.exists():
            return candidate
        raise FileNotFoundError(f"Workspace root not found: {candidate}")

    for candidate in _iter_workspace_candidates():
        resolved = candidate.expanduser()
        if resolved.exists():
            return resolved.resolve()
    raise FileNotFoundError(
        "Unable to discover llm-workspace root. Set DELAMAIN_LLM_WORKSPACE."
    )


def discover_vault_root(
    workspace_root: Path, explicit_root: str | Path | None = None
) -> Path:
    if explicit_root:
        candidate = Path(explicit_root).expanduser().resolve()
        if candidate.exists():
            return candidate
        raise FileNotFoundError(f"Vault root not found: {candidate}")

    for candidate in _iter_vault_candidates(workspace_root):
        resolved = candidate.expanduser()
        if resolved.exists():
            return resolved.resolve()
    raise FileNotFoundError("Unable to discover Vault root. Set DELAMAIN_VAULT_ROOT.")


def detect_runtime() -> str:
    if os.name == "nt":
        return "windows-native"
    if "microsoft" in platform.release().lower():
        return "wsl"
    return "unix"


def discover_runtime_paths(
    workspace_root: str | Path | None = None, vault_root: str | Path | None = None
) -> RuntimePaths:
    ws_root = discover_workspace_root(workspace_root)
    vt_root = discover_vault_root(ws_root, vault_root)

    return RuntimePaths(
        workspace_root=ws_root,
        vault_root=vt_root,
        syllabi_root=ws_root / "syllabi",
        reference_root=ws_root / "reference",
        transfer_root=ws_root / "transfer",
        vault_index_root=ws_root / "vault-index",
        skeleton_root=ws_root / "skeleton_ref",
    )


def ensure_base_layout(paths: RuntimePaths) -> None:
    for path in [
        paths.syllabi_root,
        paths.reference_root,
        paths.transfer_root,
        paths.vault_index_root,
        paths.skeleton_root / "category-template",
        paths.skeleton_root / "bundle-template",
    ]:
        path.mkdir(parents=True, exist_ok=True)

    for category in ("syllabi", "reference"):
        root = paths.category_root(category)
        (root / "_long-term").mkdir(parents=True, exist_ok=True)
