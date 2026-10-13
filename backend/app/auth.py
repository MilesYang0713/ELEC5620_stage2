"""Small, backend-only owner session support for the local prototype.

This is deliberately not a replacement for a hosted identity provider.  It keeps
the configured owner password on the server, issues opaque in-memory tokens, and
is useful for demonstrating role-gated owner operations in a local presentation.
"""

import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Header, HTTPException

SESSION_TTL_HOURS = 8
SESSIONS: dict[str, dict[str, datetime | str]] = {}


def enabled() -> bool:
    return os.getenv("AUTH_REQUIRED", "false").strip().lower() in {"1", "true", "yes"}


def configured() -> bool:
    return bool(os.getenv("OWNER_EMAIL", "").strip() and os.getenv("OWNER_PASSWORD", ""))


def _credentials() -> tuple[str, str]:
    if not configured():
        raise HTTPException(status_code=503, detail="Owner login is enabled but OWNER_EMAIL and OWNER_PASSWORD are not configured on the server.")
    return os.environ["OWNER_EMAIL"].strip(), os.environ["OWNER_PASSWORD"]


def _session_payload(email: str) -> dict[str, str]:
    return {"email": email, "name": "Jordan Mitchell", "role": "Store owner"}


def login(email: str, password: str) -> tuple[str, dict[str, str]]:
    expected_email, expected_password = _credentials()
    if not (hmac.compare_digest(email.strip().lower(), expected_email.lower()) and hmac.compare_digest(password, expected_password)):
        raise HTTPException(status_code=401, detail="Email or password is incorrect.")
    token = secrets.token_urlsafe(32)
    SESSIONS[token] = {"email": expected_email, "expires_at": datetime.now(timezone.utc) + timedelta(hours=SESSION_TTL_HOURS)}
    return token, _session_payload(expected_email)


def token_from_header(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    return token if scheme.lower() == "bearer" and token else None


def session_for_token(token: str | None) -> dict[str, str] | None:
    if not token:
        return None
    stored = SESSIONS.get(token)
    if not stored:
        return None
    expires_at = stored["expires_at"]
    if not isinstance(expires_at, datetime) or expires_at <= datetime.now(timezone.utc):
        SESSIONS.pop(token, None)
        return None
    email = stored["email"]
    return _session_payload(str(email))


def require_owner(authorization: str | None = Header(default=None)) -> dict[str, str]:
    if not enabled():
        return _session_payload("local-owner@prototype.invalid")
    session = session_for_token(token_from_header(authorization))
    if session is None:
        raise HTTPException(status_code=401, detail="Sign in as the store owner to continue.")
    return session


def logout(authorization: str | None) -> None:
    token = token_from_header(authorization)
    if token:
        SESSIONS.pop(token, None)
