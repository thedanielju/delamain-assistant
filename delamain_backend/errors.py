class DelamainError(Exception):
    """Base exception with a stable user-visible code."""

    code = "DELAMAIN_ERROR"


class DependencyBlockedError(DelamainError):
    code = "DEPENDENCY_BLOCKED"


class ConfigError(DelamainError):
    code = "CONFIG_ERROR"


class ToolPolicyDenied(DelamainError):
    code = "TOOL_POLICY_DENIED"


class SensitiveLocked(DelamainError):
    code = "SENSITIVE_LOCKED"


class ToolExecutionError(DelamainError):
    code = "TOOL_EXECUTION_ERROR"
