"""Structured schemas shared across the project (tool errors, and later
the escalation payload / provenance mapping mentioned in the spec).

Defined once here and reused everywhere they're needed, rather than letting
each component (MCP server, Coordinator, specialists) invent its own variant.
"""

from typing import Any, Literal, TypedDict

ErrorCategory = Literal["not_found", "invalid_input", "access_failure"]


class ToolError(TypedDict):
    errorCategory: ErrorCategory
    isRetryable: bool
    retryAfterMs: int | None
    partialResult: Any | None
    suggestion: str


def tool_error(
    category: ErrorCategory,
    *,
    retryable: bool,
    suggestion: str,
    retry_after_ms: int | None = None,
    partial_result: Any | None = None,
) -> ToolError:
    return {
        "errorCategory": category,
        "isRetryable": retryable,
        "retryAfterMs": retry_after_ms,
        "partialResult": partial_result,
        "suggestion": suggestion,
    }
