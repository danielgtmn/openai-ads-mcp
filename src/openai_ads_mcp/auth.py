"""Bearer authentication for the MCP endpoint.

``/health`` stays unauthenticated so container health checks can call it.
Every other request under ``/mcp`` must send ``Authorization: Bearer <MCP_AUTH_TOKEN>``.
The middleware is raw ASGI so it does not buffer Streamable HTTP response bodies.
"""

from __future__ import annotations

import secrets
from collections.abc import Awaitable, Callable
from typing import Any

Scope = dict[str, Any]
Receive = Callable[[], Awaitable[dict[str, Any]]]
Send = Callable[[dict[str, Any]], Awaitable[None]]


def _path(scope: Scope) -> str:
    path = scope.get("path") or ""
    return path if isinstance(path, str) else ""


def _requires_auth(path: str) -> bool:
    return path == "/mcp" or path.startswith("/mcp/")


def _authorization_header(scope: Scope) -> str:
    headers = scope.get("headers") or []
    for key, value in headers:
        if key.lower() == b"authorization":
            return bytes(value).decode("latin-1")
    return ""


def bearer_matches(header_value: str, expected_token: str) -> bool:
    """Return True when the header is ``Bearer`` plus the configured token."""

    scheme, separator, presented = header_value.partition(" ")
    if separator != " " or scheme.lower() != "bearer" or not presented or " " in presented:
        return False
    return secrets.compare_digest(presented, expected_token)


class BearerAuthMiddleware:
    """Require the configured bearer token on ``/mcp`` only."""

    def __init__(self, app: Callable[..., Any], token: str) -> None:
        self.app = app
        self._token = token

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        path = _path(scope)
        if _requires_auth(path) and not bearer_matches(_authorization_header(scope), self._token):
            await _send_unauthorized(send)
            return
        await self.app(scope, receive, send)


async def _send_unauthorized(send: Send) -> None:
    body = b'{"error":"Unauthorized"}'
    await send(
        {
            "type": "http.response.start",
            "status": 401,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("ascii")),
                (b"www-authenticate", b"Bearer"),
                (b"cache-control", b"no-store"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})
