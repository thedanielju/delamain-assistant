from __future__ import annotations

from delamain_backend.errors import DelamainError

class MaxToolIterationsExceeded(DelamainError):
    code = "MAX_TOOL_ITERATIONS"

    pass


def check_tool_iteration(iteration: int, max_iterations: int) -> None:
    if iteration >= max_iterations:
        raise MaxToolIterationsExceeded(
            f"Tool iteration limit reached: {max_iterations}"
        )
