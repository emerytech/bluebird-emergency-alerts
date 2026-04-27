from __future__ import annotations

import hmac
from typing import Optional

from fastapi import Header, HTTPException, Request, status

from app.services.session_store import SessionRecord


async def require_api_key(request: Request, x_api_key: Optional[str] = Header(default=None, alias="X-API-Key")) -> None:
    """
    Lightweight auth for MVP.

    If `API_KEY` is set in environment, callers must include `X-API-Key: <value>`.
    In production, replace this with per-user auth (OIDC/SAML) + audit logging.
    """

    settings = request.app.state.settings  # type: ignore[attr-defined]
    required = getattr(settings, "API_KEY", None)
    if not required:
        return

    presented = x_api_key or ""
    if not hmac.compare_digest(presented, required):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid API key",
        )


async def optional_session_token(
    request: Request,
    x_session_token: Optional[str] = Header(default=None, alias="X-Session-Token"),
) -> Optional[SessionRecord]:
    """Non-breaking: returns the validated SessionRecord if X-Session-Token is present and active, else None.

    Never raises — callers decide what to do with a missing/invalid token.
    Existing X-API-Key flows are completely unaffected.
    """
    if not x_session_token:
        return None
    tenant = getattr(request.app.state, "tenant_manager", None)
    if tenant is None:
        return None
    school = getattr(request.state, "school", None)
    if school is None:
        return None
    ctx = tenant.get(school)
    return await ctx.session_store.get_by_token(x_session_token)

