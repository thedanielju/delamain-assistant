from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from delamain_backend.config import AppConfig
from delamain_backend.errors import SensitiveLocked, ToolPolicyDenied

BINARY_EXTENSIONS = {
    ".7z",
    ".avif",
    ".bin",
    ".bmp",
    ".class",
    ".dll",
    ".doc",
    ".docx",
    ".dylib",
    ".exe",
    ".gif",
    ".gz",
    ".heic",
    ".ico",
    ".jar",
    ".jpeg",
    ".jpg",
    ".mov",
    ".mp3",
    ".mp4",
    ".odt",
    ".pdf",
    ".png",
    ".ppt",
    ".pptx",
    ".pyc",
    ".so",
    ".sqlite",
    ".tar",
    ".webp",
    ".xls",
    ".xlsx",
    ".zip",
}

PRIVATE_KEY_NAMES = {
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
    "id_rsa",
}


@dataclass(frozen=True)
class PathPolicyDecision:
    path: Path
    root_name: str
    sensitive: bool


class PathPolicy:
    def __init__(self, config: AppConfig):
        self.config = config
        self._roots = {
            "vault": config.paths.vault,
            "llm_workspace": config.paths.llm_workspace,
            "sensitive": config.paths.sensitive,
        }

    def check(
        self,
        raw_path: str,
        *,
        operation: str,
        sensitive_unlocked: bool,
        allow_binary: bool = False,
        must_exist: bool = True,
    ) -> PathPolicyDecision:
        candidate = Path(raw_path).expanduser()
        if not candidate.is_absolute():
            raise ToolPolicyDenied("Path must be absolute")
        if must_exist and not candidate.exists():
            raise ToolPolicyDenied(f"Path does not exist: {candidate}")

        resolved = candidate.resolve(strict=must_exist)
        root_name = self._root_for(resolved)
        if root_name is None:
            raise ToolPolicyDenied(f"Path is outside allowed roots: {resolved}")

        sensitive = root_name == "sensitive"
        if sensitive and not sensitive_unlocked:
            raise SensitiveLocked("Sensitive vault is locked for this conversation")

        if self.is_restricted_path(resolved, allow_binary=allow_binary):
            raise ToolPolicyDenied(f"Path is restricted by backend policy: {resolved}")

        return PathPolicyDecision(path=resolved, root_name=root_name, sensitive=sensitive)

    def is_restricted_path(self, path: Path, *, allow_binary: bool = False) -> bool:
        parts = [part.lower() for part in path.parts]
        name = path.name.lower()
        suffix = path.suffix.lower()

        if name == ".env" or name.startswith(".env."):
            return True
        if name in PRIVATE_KEY_NAMES:
            return True
        if suffix in {".pem", ".key", ".p12", ".pfx"}:
            return True
        if any(part in {".ssh", ".gnupg"} for part in parts):
            return True
        if "syncthing" in parts and name == "config.xml":
            return True
        if any(marker in name for marker in ["oauth", "token", "credential", "secret"]):
            return True
        if not allow_binary and suffix in BINARY_EXTENSIONS:
            return True
        return False

    def _root_for(self, path: Path) -> str | None:
        for root_name, root_path in self._roots.items():
            root = root_path.expanduser().resolve(strict=False)
            if path == root or root in path.parents:
                return root_name
        return None
