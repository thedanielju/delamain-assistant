from __future__ import annotations

from importlib import metadata

from delamain_backend.errors import DependencyBlockedError


KNOWN_BAD_LITELLM_VERSIONS = {"1.82.7", "1.82.8"}


def get_litellm_version() -> str | None:
    try:
        return metadata.version("litellm")
    except metadata.PackageNotFoundError:
        return None


def assert_litellm_version_allowed(version: str | None = None) -> str | None:
    observed = version if version is not None else get_litellm_version()
    if observed in KNOWN_BAD_LITELLM_VERSIONS:
        raise DependencyBlockedError(
            f"LiteLLM version {observed} is blocked for DELAMAIN"
        )
    return observed
