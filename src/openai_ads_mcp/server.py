"""Streamable HTTP MCP server for the OpenAI Ads Advertiser API."""

from __future__ import annotations

import logging
import sys

import uvicorn
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse

from openai_ads_mcp import __version__
from openai_ads_mcp.auth import BearerAuthMiddleware
from openai_ads_mcp.client import AdsClient
from openai_ads_mcp.config import Settings
from openai_ads_mcp.errors import ConfigError, redact
from openai_ads_mcp.tools import register_tools

logger = logging.getLogger("openai_ads_mcp")


def create_server(settings: Settings, client: AdsClient | None = None) -> tuple[FastMCP, AdsClient]:
    """Build a FastMCP server. Write tools exist only when settings.read_only is false."""

    ads = client or AdsClient(
        settings.openai_ads_api_key,
        base_url=settings.base_url,
        timeout=settings.request_timeout_seconds,
        max_retries=settings.max_retries,
        retry_base_seconds=settings.retry_base_seconds,
        retry_max_seconds=settings.retry_max_seconds,
        endpoint_rate_limit=settings.endpoint_rate_limit,
        global_rate_limit=settings.global_rate_limit,
        rate_window_seconds=settings.rate_window_seconds,
        max_pages=settings.max_pages,
    )
    mode = "read-only" if settings.read_only else "read and write"
    # Loopback binds keep the SDK localhost Host allowlist. A container bind
    # such as 0.0.0.0 accepts the proxy's Host header; /mcp still requires the bearer token.
    if settings.host in {"127.0.0.1", "localhost", "::1"}:
        transport_security = TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=["127.0.0.1:*", "localhost:*", "[::1]:*"],
            allowed_origins=["http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*"],
        )
    else:
        transport_security = TransportSecuritySettings(enable_dns_rebinding_protection=False)
    mcp = FastMCP(
        "openai-ads",
        instructions=(
            "Unofficial MCP server for one OpenAI Ads ad account. "
            f"Version {__version__}. Mode: {mode}. "
            "The Ads API key stays on the server. "
            "New campaigns, ad groups, and ads are created paused. "
            "Archiving is irreversible and requires confirm=true on an update."
        ),
        host=settings.host,
        port=settings.port,
        streamable_http_path="/mcp",
        json_response=True,
        stateless_http=True,
        transport_security=transport_security,
        log_level=settings.log_level,  # type: ignore[arg-type]
    )
    # FastMCP reports the SDK version unless this is set on the low-level server.
    mcp._mcp_server.version = __version__
    register_tools(mcp, ads, read_only=settings.read_only)

    @mcp.custom_route("/health", methods=["GET"])
    async def health(_request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    return mcp, ads


def build_app(settings: Settings, client: AdsClient | None = None):
    """Return the ASGI app with bearer auth on /mcp and an open /health route."""

    mcp, ads = create_server(settings, client)
    return BearerAuthMiddleware(mcp.streamable_http_app(), settings.mcp_auth_token), mcp, ads


def main() -> None:
    """Load configuration and serve Streamable HTTP on HOST:PORT."""

    try:
        settings = Settings.from_env()
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc

    _configure_logging(settings)
    app, _mcp, _client = build_app(settings)
    logger.info(
        "Starting OpenAI Ads MCP %s on %s:%s (%s).",
        __version__,
        settings.host,
        settings.port,
        "read-only" if settings.read_only else "writes enabled",
    )
    uvicorn.run(app, host=settings.host, port=settings.port, log_level=settings.log_level.lower())


def _configure_logging(settings: Settings) -> None:
    logging.basicConfig(level=settings.log_level, format="%(levelname)s %(name)s %(message)s")
    redactor = _RedactionFilter((settings.openai_ads_api_key, settings.mcp_auth_token))
    logging.getLogger().addFilter(redactor)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


class _RedactionFilter(logging.Filter):
    def __init__(self, secrets: tuple[str, ...]) -> None:
        super().__init__()
        self._secrets = tuple(secret for secret in secrets if secret)

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        cleaned = redact(message, self._secrets)
        if cleaned != message:
            record.msg = cleaned
            record.args = ()
        return True
