"""Ads API client with mocked HTTP."""

import json

import httpx
import pytest

from openai_ads_mcp.client import AdsClient
from openai_ads_mcp.errors import AdsApiError

API_KEY = "super-secret-api-key"


def client_for(handler, **kwargs) -> AdsClient:
    return AdsClient(
        API_KEY,
        transport=httpx.MockTransport(handler),
        endpoint_rate_limit=1000,
        global_rate_limit=1000,
        **kwargs,
    )


@pytest.mark.asyncio
async def test_get_ad_account_sends_bearer_token_under_v1() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert str(request.url) == "https://api.ads.openai.com/v1/ad_account"
        assert request.headers["authorization"] == f"Bearer {API_KEY}"
        return httpx.Response(
            200,
            json={
                "id": "adacct_123",
                "name": "Acme Ads",
                "url": "https://example.com",
                "preview_url": None,
                "status": "active",
                "timezone": "UTC",
                "currency_code": "USD",
                "review": {"status": "approved"},
            },
        )

    client = client_for(handler)
    body = await client.get_ad_account()
    assert body["id"] == "adacct_123"
    assert body["status"] == "active"
    await client.aclose()


@pytest.mark.asyncio
async def test_list_campaigns_follows_cursor() -> None:
    seen: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        after = request.url.params.get("after")
        seen.append(after)
        if after is None:
            return httpx.Response(
                200,
                json={
                    "object": "list",
                    "data": [{"id": "cmpn_1", "status": "paused"}],
                    "first_id": "cmpn_1",
                    "last_id": "cmpn_1",
                    "has_more": True,
                },
            )
        assert after == "cmpn_1"
        return httpx.Response(
            200,
            json={
                "object": "list",
                "data": [{"id": "cmpn_2", "status": "active"}],
                "first_id": "cmpn_2",
                "last_id": "cmpn_2",
                "has_more": False,
            },
        )

    client = client_for(handler)
    page = await client.list_campaigns(limit=2, order="desc", include_serving_issues=True)
    assert [row["id"] for row in page["data"]] == ["cmpn_1", "cmpn_2"]
    assert page["pages_fetched"] == 2
    assert page["truncated"] is False
    assert seen == [None, "cmpn_1"]
    await client.aclose()


@pytest.mark.asyncio
async def test_before_cursor_does_not_auto_follow() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert request.url.params.get("before") == "cmpn_2"
        return httpx.Response(
            200,
            json={
                "object": "list",
                "data": [{"id": "cmpn_1"}],
                "first_id": "cmpn_1",
                "last_id": "cmpn_1",
                "has_more": True,
            },
        )

    client = client_for(handler)
    page = await client.list_campaigns(before="cmpn_2", fetch_all=True)
    assert calls == 1
    assert page["has_more"] is True
    assert page["truncated"] is False
    await client.aclose()


@pytest.mark.asyncio
async def test_retries_429_with_same_idempotency_key() -> None:
    keys: list[str | None] = []
    delays: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        keys.append(request.headers.get("idempotency-key"))
        if len(keys) < 3:
            return httpx.Response(
                429,
                headers={"retry-after": "0.25"},
                json={"error": {"message": "slow down", "code": "rate_limit"}},
            )
        return httpx.Response(200, json={"id": "cmpn_1", "status": "paused"})

    async def sleep(seconds: float) -> None:
        delays.append(seconds)

    client = client_for(handler, sleep=sleep, max_retries=4)
    body = await client.create_campaign(
        {"name": "Launch", "status": "paused", "budget": {"lifetime_spend_limit_micros": 1000000}},
        idempotency_key="create-1",
    )
    assert body["id"] == "cmpn_1"
    assert keys == ["create-1", "create-1", "create-1"]
    assert delays == [0.25, 0.25]
    await client.aclose()


@pytest.mark.asyncio
async def test_error_message_redacts_the_api_key_and_does_not_retry_400() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            401,
            json={"error": {"message": f"rejected {API_KEY}", "type": "authentication_error", "code": "invalid_api_key"}},
        )

    client = client_for(handler, max_retries=3)
    with pytest.raises(AdsApiError, match="Authentication failed") as caught:
        await client.get_ad_account()
    text = str(caught.value)
    assert API_KEY not in text
    assert "[redacted]" in text
    assert "401" in text
    assert "invalid_api_key" in text
    assert calls == 1
    await client.aclose()


@pytest.mark.asyncio
async def test_does_not_follow_redirects() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "https://evil.example/collect"})

    client = client_for(handler)
    with pytest.raises(AdsApiError, match="does not follow redirects"):
        await client.get_ad_account()
    await client.aclose()


@pytest.mark.asyncio
async def test_insights_request_shape() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/campaigns/cmpn_101/insights"
        assert request.url.params.get("time_granularity") == "daily"
        assert request.url.params.get("aggregation_level") == "ad"
        fields = request.url.params.get_list("fields[]")
        for metric in ("impressions", "clicks", "spend", "ctr", "cpc"):
            assert f"ad.{metric}" in fields
        time_range = json.loads(request.url.params.get("time_ranges[]") or "")
        assert time_range == {
            "type": "date_range",
            "since": "2026-04-01",
            "until": "2026-04-07",
            "timezone": "America/New_York",
        }
        return httpx.Response(
            200,
            json={
                "object": "list",
                "data": [{"impressions": 10, "clicks": 2, "spend": 1.5, "ctr": 0.2, "cpc": 0.75}],
                "has_more": False,
                "first_id": "row1",
                "last_id": "row1",
                "timezone": "America/New_York",
            },
        )

    client = client_for(handler)
    report = await client.get_insights(
        level="campaign",
        campaign_id="cmpn_101",
        start_date="2026-04-01",
        end_date="2026-04-07",
        aggregation_level="ad",
        timezone_name="America/New_York",
    )
    assert report["metrics"] == ["impressions", "clicks", "spend", "ctr", "cpc"]
    assert report["data"][0]["ctr"] == 0.2
    await client.aclose()


@pytest.mark.asyncio
async def test_insights_rejects_aggregation_above_the_endpoint() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("invalid insights requests must not be sent")

    client = client_for(handler)
    with pytest.raises(AdsApiError, match="above"):
        await client.get_insights(
            level="ad",
            ad_id="ad_1",
            start_date="2026-04-01",
            end_date="2026-04-02",
            aggregation_level="campaign",
        )
    await client.aclose()


@pytest.mark.asyncio
async def test_client_logs_do_not_include_the_api_key(caplog: pytest.LogCaptureFixture) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": {"message": "missing"}})

    client = client_for(handler)
    with caplog.at_level("INFO", logger="openai_ads_mcp.client"):
        with pytest.raises(AdsApiError):
            await client.get_campaign("cmpn_missing")
    assert API_KEY not in caplog.text
    await client.aclose()
