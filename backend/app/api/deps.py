from __future__ import annotations

import hmac
from typing import Optional

from fastapi import Header, HTTPException, Request, status


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

