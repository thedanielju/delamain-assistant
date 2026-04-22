from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from delamain_backend.errors import ConfigError


@dataclass(frozen=True)
class ServerConfig:
    host: str
    port: int


@dataclass(frozen=True)
class DatabaseConfig:
    path: Path


@dataclass(frozen=True)
class PathsConfig:
    vault: Path
    sensitive: Path
    llm_workspace: Path

    @property
    def system_context(self) -> Path:
        return self.llm_workspace / "context" / "system-context.md"

    @property
    def short_term_continuity(self) -> Path:
        return self.llm_workspace / "context" / "short-term" / "continuity.md"


@dataclass(frozen=True)
class ModelsConfig:
    default: str
    fallback_high_volume: str
    fallback_cheap: str
    paid_fallback: str


@dataclass(frozen=True)
class ToolsConfig:
    max_tool_iterations: int
    default_timeout_seconds: int
    output_limit_bytes: int


@dataclass(frozen=True)
class RuntimeConfig:
    enable_model_calls: bool
    disable_model_fallbacks: bool
    model_timeout_seconds: int


@dataclass(frozen=True)
class AuthConfig:
    mode: str
    allowed_email: str
    cloudflare_access_team_domain: str
    cloudflare_access_audience: str
    cloudflare_access_jwks_url: str

    @property
    def issuer(self) -> str:
        domain = self.cloudflare_access_team_domain.strip().rstrip("/")
        if not domain:
            return ""
        if domain.startswith("https://"):
            return domain
        return f"https://{domain}"

    @property
    def jwks_url(self) -> str:
        if self.cloudflare_access_jwks_url:
            return self.cloudflare_access_jwks_url
        issuer = self.issuer
        return f"{issuer}/cdn-cgi/access/certs" if issuer else ""


@dataclass(frozen=True)
class MaintenanceConfig:
    action_output_retention_days: int
    context_backup_retention_days: int


@dataclass(frozen=True)
class AppConfig:
    server: ServerConfig
    database: DatabaseConfig
    paths: PathsConfig
    models: ModelsConfig
    tools: ToolsConfig
    runtime: RuntimeConfig
    auth: AuthConfig
    maintenance: MaintenanceConfig


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ConfigError(f"Config file does not exist: {path}")
    with path.open("r", encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle) or {}
    if not isinstance(loaded, dict):
        raise ConfigError(f"Config file must contain a mapping: {path}")
    return loaded


def _as_bool(value: str | bool | None, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return value.strip().lower() in {"1", "true", "yes", "on"}


def load_config(config_path: str | Path | None = None) -> AppConfig:
    path = Path(
        config_path
        or os.environ.get("DELAMAIN_CONFIG")
        or (_project_root() / "config" / "defaults.yaml")
    )
    raw = _read_yaml(path)

    server = raw.get("server", {})
    database = raw.get("database", {})
    paths = raw.get("paths", {})
    models = raw.get("models", {})
    tools = raw.get("tools", {})
    runtime = raw.get("runtime", {})
    auth = raw.get("auth", {})
    maintenance = raw.get("maintenance", {})

    db_path = Path(os.environ.get("DELAMAIN_DB_PATH", database["path"])).expanduser()
    enable_model_calls = _as_bool(
        os.environ.get("DELAMAIN_ENABLE_MODEL_CALLS"),
        bool(runtime.get("enable_model_calls", False)),
    )
    disable_model_fallbacks = _as_bool(
        os.environ.get("DELAMAIN_DISABLE_MODEL_FALLBACKS"),
        bool(runtime.get("disable_model_fallbacks", False)),
    )
    model_timeout_seconds = int(
        os.environ.get(
            "DELAMAIN_MODEL_TIMEOUT_SECONDS",
            runtime.get("model_timeout_seconds", 30),
        )
    )

    return AppConfig(
        server=ServerConfig(host=str(server["host"]), port=int(server["port"])),
        database=DatabaseConfig(path=db_path),
        paths=PathsConfig(
            vault=Path(paths["vault"]),
            sensitive=Path(paths["sensitive"]),
            llm_workspace=Path(paths["llm_workspace"]),
        ),
        models=ModelsConfig(
            default=str(models["default"]),
            fallback_high_volume=str(models["fallback_high_volume"]),
            fallback_cheap=str(models["fallback_cheap"]),
            paid_fallback=str(models["paid_fallback"]),
        ),
        tools=ToolsConfig(
            max_tool_iterations=int(tools["max_tool_iterations"]),
            default_timeout_seconds=int(tools["default_timeout_seconds"]),
            output_limit_bytes=int(tools["output_limit_bytes"]),
        ),
        runtime=RuntimeConfig(
            enable_model_calls=enable_model_calls,
            disable_model_fallbacks=disable_model_fallbacks,
            model_timeout_seconds=model_timeout_seconds,
        ),
        auth=AuthConfig(
            mode=str(os.environ.get("DELAMAIN_AUTH_MODE", auth.get("mode", "dev_local"))),
            allowed_email=str(
                os.environ.get("DELAMAIN_AUTH_ALLOWED_EMAIL", auth.get("allowed_email", ""))
            ),
            cloudflare_access_team_domain=str(
                os.environ.get(
                    "DELAMAIN_CF_ACCESS_TEAM_DOMAIN",
                    auth.get("cloudflare_access_team_domain", ""),
                )
            ),
            cloudflare_access_audience=str(
                os.environ.get(
                    "DELAMAIN_CF_ACCESS_AUDIENCE",
                    auth.get("cloudflare_access_audience", ""),
                )
            ),
            cloudflare_access_jwks_url=str(
                os.environ.get(
                    "DELAMAIN_CF_ACCESS_JWKS_URL",
                    auth.get("cloudflare_access_jwks_url", ""),
                )
            ),
        ),
        maintenance=MaintenanceConfig(
            action_output_retention_days=int(
                os.environ.get(
                    "DELAMAIN_ACTION_OUTPUT_RETENTION_DAYS",
                    maintenance.get("action_output_retention_days", 30),
                )
            ),
            context_backup_retention_days=int(
                os.environ.get(
                    "DELAMAIN_CONTEXT_BACKUP_RETENTION_DAYS",
                    maintenance.get("context_backup_retention_days", 30),
                )
            ),
        ),
    )
