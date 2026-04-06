"""Enterprise AI Platform — ApiKeyVerifier service class."""
from __future__ import annotations

import hmac
import os
from typing import Callable, Optional

from ..logging import get_logger

log = get_logger(__name__)


class ApiKeyVerifier:
    """
    Service class that wraps the make_api_key_verifier factory function.

    Provides FastAPI dependency for Bearer token validation against INTERNAL_API_KEY.
    """

    def __init__(self, api_key: Optional[str] = None) -> None:
        """
        Initialize ApiKeyVerifier with an optional static API key.

        Args:
            api_key: Optional static API key to use for all requests.
                     If None, the key is read from INTERNAL_API_KEY environment
                     variable at verification time (safer for late-binding test setups).
        """
        self._api_key = api_key

    def create_dependency(self) -> Callable:
        """
        Create and return a FastAPI dependency function for Bearer token validation.

        The returned function validates Bearer tokens against the configured API key
        using constant-time comparison (hmac.compare_digest).

        Returns:
            An async callable that can be used as a FastAPI dependency.
            The callable expects HTTPAuthorizationCredentials and returns the
            valid token, or raises HTTPException on failure.

        Raises:
            HTTPException: 401 if token is invalid, 500 if API key is not configured.

        Usage:
            verify = ApiKeyVerifier().create_dependency()

            @app.post("/endpoint")
            async def endpoint(_: str = Depends(verify)):
                ...
        """
        # Lazy FastAPI import — services without FastAPI (e.g. MCP servers) can
        # still import the rest of this module without pulling in FastAPI.
        from fastapi import HTTPException, Security
        from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

        _bearer = HTTPBearer(auto_error=True)

        # Capture the key at verifier-creation time if provided; otherwise read
        # from environment on every request (safer for late-binding test setups).
        _static_key: Optional[str] = self._api_key

        async def _verify(
            credentials: HTTPAuthorizationCredentials = Security(_bearer),
        ) -> str:
            key = _static_key or os.environ.get("INTERNAL_API_KEY", "")
            if not key:
                log.error("auth_misconfigured", reason="INTERNAL_API_KEY not set")
                raise HTTPException(
                    status_code=500,
                    detail="Service temporarily unavailable. Contact your administrator.",
                )
            if not hmac.compare_digest(credentials.credentials, key):
                log.warning("auth_rejected", reason="invalid_api_key")
                raise HTTPException(status_code=401, detail="Unauthorized")
            return credentials.credentials

        return _verify
