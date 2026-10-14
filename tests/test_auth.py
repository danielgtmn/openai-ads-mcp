"""HTTP auth: /health is open and /mcp requires the bearer token."""

import httpx
import pytest
from mcp.types import LATEST_PROTOCOL_VERSION
from starlette.testclient import TestClient

from openai_ads_mcp.client import AdsClient
from openai_ads_mcp.config import Settings
from openai_ads_mcp.server import build_app

TOKEN = "mcp-test-token-value"


def _settings() -> Settings:
    return Settings(
        openai_ads_api_key="super-secret-api-key",
        mcp_auth_token=TOKEN,
        read_only=True,
        host="0.0.0.0",
        port=8765,
        base_url="https://api.ads.openai.com/v1",
        log_level="WARNING",
        endpoint_rate_limit=1000,
        global_rate_limit=1000,
        rate_window_seconds=60,
        max_retries=0,
        retry_base_seconds=0,
        retry_max_seconds=0,
        request_timeout_seconds=5,
        max_pages=2,
    )


@pytest.fixture
def app():
    client = AdsClient(
        "super-secret-api-key",
        transport=httpx.MockTransport(lambda _request: httpx.Response(500, json={"error": {"message": "unused"}})),
    )
    asgi, _mcp, ads = build_app(_settings(), client)
    yield asgi
    # The mock client is closed with the server lifespan when possible.


def test_health_is_open_and_mcp_requires_bearer(app) -> None:
    with TestClient(app) as http:
        health = http.get("/health")
        assert health.status_code == 200
        assert health.json() == {"status": "ok"}

        missing = http.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        assert missing.status_code == 401
        assert missing.json() == {"error": "Unauthorized"}
        assert missing.headers["www-authenticate"] == "Bearer"
        assert TOKEN not in missing.text

        wrong = http.post(
            "/mcp",
            headers={"Authorization": "Bearer not-the-token"},
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        )
        assert wrong.status_code == 401

        accepted = http.post(
            "/mcp",
            headers={
                "Authorization": f"Bearer {TOKEN}",
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            },
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": LATEST_PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "0"},
                },
            },
        )
        assert accepted.status_code == 200
        body = accepted.json()
        assert body["result"]["serverInfo"]["name"] == "openai-ads"
        assert body["result"]["serverInfo"]["version"] == "0.1.0"
        assert TOKEN not in accepted.text
