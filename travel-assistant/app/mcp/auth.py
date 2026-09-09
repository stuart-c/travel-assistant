"""Authentication middleware for the MCP service."""

import logging
from typing import Any, Callable
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logger = logging.getLogger(__name__)


class BearerAuthMiddleware(BaseHTTPMiddleware):
    """Starlette middleware enforcing Bearer token authentication when configured."""

    def __init__(self, app: Callable[..., Any], api_token: str = "") -> None:
        super().__init__(app)
        self.api_token = str(api_token).strip()

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Any]
    ) -> Response:
        if self.api_token:
            auth_header = request.headers.get("authorization", "").strip()
            if not auth_header.startswith("Bearer "):
                logger.warning(
                    "Unauthorized MCP request to %s: Missing Bearer token.",
                    request.url.path,
                )
                return JSONResponse(
                    {
                        "error": "Unauthorized",
                        "message": "Missing or invalid Bearer authentication token.",
                    },
                    status_code=401,
                )

            token = auth_header[7:].strip()
            if token != self.api_token:
                logger.warning(
                    "Unauthorized MCP request to %s: Invalid token supplied.",
                    request.url.path,
                )
                return JSONResponse(
                    {
                        "error": "Unauthorized",
                        "message": "Invalid Bearer authentication token.",
                    },
                    status_code=401,
                )

        return await call_next(request)


__all__ = ["BearerAuthMiddleware"]
