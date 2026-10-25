"""Safe structured diagnostics for LLM analysis failures."""

import json
import logging
from typing import Any


_logger = logging.getLogger("app.llm_diagnostics")


def classify_error(error: BaseException) -> str:
    error_name = type(error).__name__.lower()
    status = getattr(error, "status_code", None)
    if not isinstance(status, int):
        status = getattr(getattr(error, "response", None), "status_code", None)
    if status == 429 or "ratelimit" in error_name:
        return "rate_limit"
    if status in (500, 502, 503, 504) or any(term in error_name for term in ("internalserver", "serviceunavailable")):
        return "server_error"
    if status in (401, 403) or "authentication" in error_name or "permission" in error_name:
        return "authentication"
    if "configuration" in error_name:
        return "configuration"
    if "timeout" in error_name:
        return "timeout"
    if any(term in error_name for term in ("connection", "network", "transport", "urlerror")):
        return "connection"
    if any(term in error_name for term in ("response", "json", "validation", "parse", "format")):
        return "invalid_response"
    return "unexpected"


def retryable_error_category(error: BaseException) -> str | None:
    """Retry known transient transport and provider failures, never validation or auth."""
    category = classify_error(error)
    return category if category in {"timeout", "connection", "rate_limit", "server_error"} else None


def log_agent_failure(
    *,
    analysis_id: str,
    agent_name: str,
    error: BaseException,
    error_category: str | None = None,
    attempt: int | None = None,
    retrying: bool | None = None,
) -> None:
    """Write an allowlisted failure record without exception or provider content."""
    event: dict[str, Any] = {
        "event": "llm_agent_failure",
        "analysis_id": analysis_id,
        "agent_name": agent_name,
        "error_type": type(error).__name__,
        "error_category": error_category or classify_error(error),
    }
    if attempt is not None:
        event["attempt"] = attempt
    if retrying is not None:
        event["retrying"] = retrying
    _logger.warning("%s", json.dumps(event, separators=(",", ":"), sort_keys=True))


def log_agent_recovery(*, analysis_id: str, agent_name: str, attempt: int) -> None:
    """Record a recovered provider request; response validation happens afterward."""
    event = {"event": "llm_agent_request_recovered", "analysis_id": analysis_id,
             "agent_name": agent_name, "attempt": attempt}
    _logger.warning("%s", json.dumps(event, separators=(",", ":"), sort_keys=True))
