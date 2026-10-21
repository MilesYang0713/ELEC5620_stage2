"""Safe structured diagnostics for LLM analysis failures."""

import json
import logging
from typing import Any


_logger = logging.getLogger("app.llm_diagnostics")


def _error_category(error: BaseException) -> str:
    error_name = type(error).__name__.lower()
    if "timeout" in error_name:
        return "timeout"
    if any(term in error_name for term in ("connection", "network", "transport", "urlerror")):
        return "connection"
    if any(term in error_name for term in ("response", "json", "validation", "parse", "format")):
        return "invalid_response"
    return "unexpected"


def log_agent_failure(
    *,
    analysis_id: str,
    agent_name: str,
    error: BaseException,
    error_category: str | None = None,
) -> None:
    """Write an allowlisted failure record without exception or provider content."""
    event: dict[str, Any] = {
        "event": "llm_agent_failure",
        "analysis_id": analysis_id,
        "agent_name": agent_name,
        "error_type": type(error).__name__,
        "error_category": error_category or _error_category(error),
    }
    _logger.warning("%s", json.dumps(event, separators=(",", ":"), sort_keys=True))
