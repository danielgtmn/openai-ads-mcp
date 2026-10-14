"""Read-only Ads API tools."""

from typing import Any, Literal

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from openai_ads_mcp.client import AdsClient

_READ = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=True,
)


def register_read_tools(mcp: FastMCP, client: AdsClient) -> None:
    """Register account, list, status, and insights tools."""

    @mcp.tool(annotations=_READ)
    async def get_ad_account() -> dict[str, Any]:
        """Get the authenticated ad account (GET /ad_account).

        Returns id, names, url, status, timezone, currency_code, and review.
        """

        return await client.get_ad_account()

    @mcp.tool(annotations=_READ)
    async def list_campaigns(
        limit: int | None = None,
        after: str | None = None,
        before: str | None = None,
        order: Literal["asc", "desc"] | None = None,
        name: str | None = None,
        include_serving_issues: bool = False,
        fetch_all: bool = True,
    ) -> dict[str, Any]:
        """List campaigns in the current ad account (GET /campaigns).

        limit is 1 to 500. after and before are cursors from last_id and first_id.
        fetch_all follows has_more with after=last_id until the page cap.
        Pass before to read a single previous page without following further pages.
        """

        return await client.list_campaigns(
            limit=limit,
            after=after,
            before=before,
            order=order,
            name=name,
            include_serving_issues=include_serving_issues,
            fetch_all=fetch_all,
        )

    @mcp.tool(annotations=_READ)
    async def list_ad_groups(
        campaign_id: str,
        limit: int | None = None,
        after: str | None = None,
        before: str | None = None,
        order: Literal["asc", "desc"] | None = None,
        name: str | None = None,
        include_serving_issues: bool = False,
        fetch_all: bool = True,
    ) -> dict[str, Any]:
        """List ad groups for one campaign (GET /ad_groups?campaign_id=)."""

        return await client.list_ad_groups(
            campaign_id,
            limit=limit,
            after=after,
            before=before,
            order=order,
            name=name,
            include_serving_issues=include_serving_issues,
            fetch_all=fetch_all,
        )

    @mcp.tool(annotations=_READ)
    async def list_ads(
        ad_group_id: str,
        limit: int | None = None,
        after: str | None = None,
        before: str | None = None,
        order: Literal["asc", "desc"] | None = None,
        name: str | None = None,
        include_serving_issues: bool = False,
        fetch_all: bool = True,
    ) -> dict[str, Any]:
        """List ads for one ad group (GET /ads?ad_group_id=)."""

        return await client.list_ads(
            ad_group_id,
            limit=limit,
            after=after,
            before=before,
            order=order,
            name=name,
            include_serving_issues=include_serving_issues,
            fetch_all=fetch_all,
        )

    @mcp.tool(annotations=_READ)
    async def get_campaign_status(campaign_id: str, include_serving_issues: bool = False) -> dict[str, Any]:
        """Get one campaign, including its status (GET /campaigns/{campaign_id})."""

        resource = await client.get_campaign(campaign_id, include_serving_issues=include_serving_issues)
        return _status(resource)

    @mcp.tool(annotations=_READ)
    async def get_ad_group_status(ad_group_id: str, include_serving_issues: bool = False) -> dict[str, Any]:
        """Get one ad group, including its status (GET /ad_groups/{ad_group_id})."""

        resource = await client.get_ad_group(ad_group_id, include_serving_issues=include_serving_issues)
        return _status(resource)

    @mcp.tool(annotations=_READ)
    async def get_ad_status(ad_id: str, include_serving_issues: bool = False) -> dict[str, Any]:
        """Get one ad, including status and review_status (GET /ads/{ad_id})."""

        resource = await client.get_ad(ad_id, include_serving_issues=include_serving_issues)
        return _status(resource, review=True)

    @mcp.tool(annotations=_READ)
    async def get_performance_report(
        level: Literal["ad_account", "campaign", "ad_group", "ad"],
        start_date: str,
        end_date: str,
        campaign_id: str | None = None,
        ad_group_id: str | None = None,
        ad_id: str | None = None,
        time_granularity: Literal["hourly", "daily", "monthly", "none"] = "daily",
        aggregation_level: Literal["ad_account", "campaign", "ad_group", "ad"] | None = None,
        timezone_name: str | None = None,
        limit: int | None = None,
        fetch_all: bool = True,
    ) -> dict[str, Any]:
        """Fetch impressions, clicks, spend, CTR, and CPC for a date range.

        Uses GET /ad_account/insights, GET /campaigns/{id}/insights,
        GET /ad_groups/{id}/insights, or GET /ads/{id}/insights.
        start_date and end_date are YYYY-MM-DD. end_date is inclusive.
        Pass campaign_id, ad_group_id, or ad_id when level is not ad_account.
        """

        return await client.get_insights(
            level=level,
            start_date=start_date,
            end_date=end_date,
            campaign_id=campaign_id,
            ad_group_id=ad_group_id,
            ad_id=ad_id,
            time_granularity=time_granularity,
            aggregation_level=aggregation_level,
            timezone_name=timezone_name,
            limit=limit,
            fetch_all=fetch_all,
        )


def _status(resource: dict[str, Any], *, review: bool = False) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": resource.get("id"),
        "name": resource.get("name"),
        "status": resource.get("status"),
    }
    if review:
        payload["review_status"] = resource.get("review_status")
        if "review" in resource:
            payload["review"] = resource.get("review")
    if "serving_issues" in resource:
        payload["serving_issues"] = resource.get("serving_issues")
    payload["resource"] = resource
    return payload
