"""Tool registration and request bodies, with the Ads API mocked."""

import json

import httpx
import pytest
from mcp.server.fastmcp.exceptions import ToolError

from openai_ads_mcp.client import AdsClient
from openai_ads_mcp.config import Settings
from openai_ads_mcp.server import create_server

API_KEY = "super-secret-api-key"


def settings(*, read_only: bool) -> Settings:
    return Settings(
        openai_ads_api_key=API_KEY,
        mcp_auth_token="mcp-test-token-value",
        read_only=read_only,
        host="127.0.0.1",
        port=8000,
        base_url="https://api.ads.openai.com/v1",
        log_level="INFO",
        endpoint_rate_limit=1000,
        global_rate_limit=1000,
        rate_window_seconds=60,
        max_retries=2,
        retry_base_seconds=0,
        retry_max_seconds=0,
        request_timeout_seconds=5,
        max_pages=5,
    )


def server_with(handler, *, read_only: bool):
    client = AdsClient(
        API_KEY,
        transport=httpx.MockTransport(handler),
        endpoint_rate_limit=1000,
        global_rate_limit=1000,
        max_retries=1,
        retry_base_seconds=0,
    )
    mcp, ads = create_server(settings(read_only=read_only), client)
    return mcp, ads


READ_TOOLS = {
    "get_ad_account",
    "list_campaigns",
    "list_ad_groups",
    "list_ads",
    "get_campaign_status",
    "get_ad_group_status",
    "get_ad_status",
    "get_performance_report",
}
WRITE_TOOLS = {
    "upload_ad_image",
    "create_campaign",
    "create_ad_group",
    "create_ad",
    "pause_campaign",
    "pause_ad_group",
    "pause_ad",
    "activate_campaign",
    "activate_ad_group",
    "activate_ad",
    "update_campaign",
    "update_ad_group",
    "update_ad",
}


@pytest.mark.asyncio
async def test_read_only_server_hides_write_tools() -> None:
    mcp, client = server_with(lambda _request: httpx.Response(500), read_only=True)
    names = {tool.name for tool in await mcp.list_tools()}
    assert READ_TOOLS <= names
    assert names.isdisjoint(WRITE_TOOLS)
    with pytest.raises(ToolError, match="Unknown tool"):
        await mcp.call_tool("create_campaign", {"name": "Launch", "lifetime_spend_limit_micros": 1000000})
    await client.aclose()


@pytest.mark.asyncio
async def test_write_mode_registers_write_tools() -> None:
    mcp, client = server_with(lambda _request: httpx.Response(500), read_only=False)
    names = {tool.name for tool in await mcp.list_tools()}
    assert WRITE_TOOLS <= names
    await client.aclose()


@pytest.mark.asyncio
async def test_create_campaign_is_paused() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        captured["key"] = request.headers.get("idempotency-key")
        captured["path"] = request.url.path
        return httpx.Response(200, json={"id": "cmpn_1", "name": "Launch", "status": "paused"})

    mcp, client = server_with(handler, read_only=False)
    result = await mcp.call_tool(
        "create_campaign",
        {
            "name": "Launch",
            "lifetime_spend_limit_micros": 25000000,
            "bidding_type": "clicks",
            "idempotency_key": "first-campaign",
        },
    )
    assert captured["path"] == "/v1/campaigns"
    assert captured["body"]["status"] == "paused"
    assert captured["body"]["budget"] == {"lifetime_spend_limit_micros": 25000000}
    assert captured["key"] == "first-campaign"
    text = _tool_text(result)
    assert "paused" in text
    await client.aclose()


@pytest.mark.asyncio
async def test_create_ad_requires_image_and_stays_paused() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"id": "ad_1", "name": "Card", "status": "paused", "review_status": "in_review"},
        )

    mcp, client = server_with(handler, read_only=False)
    with pytest.raises(ToolError, match="file_id"):
        await mcp.call_tool(
            "create_ad",
            {
                "ad_group_id": "adgrp_1",
                "name": "Card",
                "creative_type": "chat_card",
                "title": "Hello there",
                "body": "Short copy",
                "target_url": "https://example.com/shoes",
            },
        )
    await mcp.call_tool(
        "create_ad",
        {
            "ad_group_id": "adgrp_1",
            "name": "Card",
            "creative_type": "chat_card",
            "title": "Hello there",
            "body": "Short copy",
            "target_url": "https://example.com/shoes",
            "file_id": "file_901",
        },
    )
    assert captured["body"]["status"] == "paused"
    assert captured["body"]["creative"]["file_id"] == "file_901"
    assert captured["body"]["creative"]["type"] == "chat_card"
    await client.aclose()


@pytest.mark.asyncio
async def test_archive_requires_confirm_and_is_not_sent_otherwise() -> None:
    called = False

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json={"id": "cmpn_1", "status": "archived"})

    mcp, client = server_with(handler, read_only=False)
    with pytest.raises(ToolError, match="confirm=true"):
        await mcp.call_tool("update_campaign", {"campaign_id": "cmpn_1", "status": "archived"})
    assert called is False

    await mcp.call_tool(
        "update_campaign",
        {"campaign_id": "cmpn_1", "status": "archived", "confirm": True},
    )
    assert called is True
    await client.aclose()


@pytest.mark.asyncio
async def test_pause_and_activate_use_dedicated_endpoints() -> None:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        assert request.content == b""
        return httpx.Response(200, json={"id": "cmpn_1", "status": "paused"})

    mcp, client = server_with(handler, read_only=False)
    await mcp.call_tool("pause_campaign", {"campaign_id": "cmpn_1"})
    await mcp.call_tool("activate_ad", {"ad_id": "ad_1"})
    assert paths == ["/v1/campaigns/cmpn_1/pause", "/v1/ads/ad_1/activate"]
    await client.aclose()


@pytest.mark.asyncio
async def test_upload_uses_image_url_json() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/upload"
        assert json.loads(request.content) == {"image_url": "https://cdn.example/card.png"}
        return httpx.Response(200, json={"file_id": "file_901"})

    mcp, client = server_with(handler, read_only=False)
    result = await mcp.call_tool("upload_ad_image", {"image_url": "https://cdn.example/card.png"})
    assert "file_901" in _tool_text(result)
    await client.aclose()


@pytest.mark.asyncio
async def test_status_tool_returns_status() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/ads/ad_501"
        assert request.url.params.get("include[]") == "serving_issues"
        return httpx.Response(
            200,
            json={
                "id": "ad_501",
                "name": "Card",
                "status": "paused",
                "review_status": "approved",
                "serving_issues": [],
            },
        )

    mcp, client = server_with(handler, read_only=True)
    result = await mcp.call_tool("get_ad_status", {"ad_id": "ad_501", "include_serving_issues": True})
    payload = json.loads(_tool_text(result))
    assert payload["status"] == "paused"
    assert payload["review_status"] == "approved"
    await client.aclose()


def _tool_text(result) -> str:
    if isinstance(result, tuple):
        structured = result[1] if len(result) > 1 else None
        if isinstance(structured, dict):
            return json.dumps(structured)
        result = result[0]
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        return json.dumps(result)
    parts: list[str] = []
    for block in result:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    return "\n".join(parts)
