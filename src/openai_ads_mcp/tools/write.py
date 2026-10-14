"""Write tools. Registered only when MCP_READ_ONLY=false.

Creates always send status=paused. Archive is not a separate tool. An update
can set status to archived only when confirm is true, because archiving is
irreversible.
"""

from typing import Any, Literal

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from openai_ads_mcp.client import AdsClient
from openai_ads_mcp.errors import AdsApiError
from openai_ads_mcp.validation import (
    bid_multipliers,
    campaign_budget,
    editable_status,
    http_url,
    image_crop,
    object_dict,
    optional_idempotency_key,
    positive_micros,
    query_template,
    resource_id,
    resource_name,
    string_list,
    unix_time,
)

_CREATE = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=False,
    idempotentHint=False,
    openWorldHint=True,
)
_STATE = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=True,
)
_UPDATE = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=True,
    idempotentHint=False,
    openWorldHint=True,
)

_PAUSED_NOTE = "Created paused. Call the matching activate tool when delivery should start."


def register_write_tools(mcp: FastMCP, client: AdsClient) -> None:
    """Register create, pause, activate, and edit tools."""

    @mcp.tool(annotations=_CREATE)
    async def upload_ad_image(image_url: str) -> dict[str, Any]:
        """Upload a remote image for an ad creative (POST /upload).

        Send JSON ``{"image_url": "..."}``. Use the returned file_id as
        creative.file_id when creating a chat_card ad. Omit purpose; account
        favicon uploads are not exposed here.
        """

        url = http_url(image_url, "image_url")
        return await client.upload_image(url)

    @mcp.tool(annotations=_CREATE)
    async def create_campaign(
        name: str,
        lifetime_spend_limit_micros: int | None = None,
        daily_spend_limit_micros: int | None = None,
        description: str | None = None,
        start_time: int | None = None,
        end_time: int | None = None,
        bidding_type: Literal["impressions", "clicks", "conversions"] | None = None,
        conversion_event_setting_ids: list[str] | None = None,
        mode: Literal["product_feed", "business_agent"] | None = None,
        product_feed_id: str | None = None,
        business_agent_id: str | None = None,
        targeting: dict[str, Any] | None = None,
        objective: Literal["reach", "clicks", "conversions"] | None = None,
        billing_event_type: Literal["impression", "click"] | None = None,
        query_string_template: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Create a paused campaign (POST /campaigns).

        status is always paused. Amounts are micros of the account currency
        (1000000 micros = 1 currency unit). Provide a lifetime limit, a daily
        limit, or both; each minimum is 1000000. bidding_type defaults to
        impressions at the API when omitted. conversions requires exactly one
        conversion_event_setting_ids entry. A product_feed campaign needs
        product_feed_id. Reuse idempotency_key to retry the same create safely.
        """

        body: dict[str, Any] = {
            "name": resource_name(name),
            "status": "paused",
            "budget": campaign_budget(lifetime_spend_limit_micros, daily_spend_limit_micros),
        }
        if description is not None:
            body["description"] = description
        start = unix_time(start_time, "start_time")
        end = unix_time(end_time, "end_time")
        if start is not None:
            body["start_time"] = start
        if end is not None:
            body["end_time"] = end
        if bidding_type is not None:
            body["bidding_type"] = bidding_type
        events = string_list(conversion_event_setting_ids, "conversion_event_setting_ids")
        if bidding_type == "conversions" and (events is None or len(events) != 1):
            raise AdsApiError("bidding_type conversions requires exactly one conversion_event_setting_ids value.")
        if events is not None:
            body["conversion_event_setting_ids"] = events
        if mode is not None:
            body["mode"] = mode
        if mode == "product_feed" and not product_feed_id:
            raise AdsApiError("mode product_feed requires product_feed_id.")
        if mode == "business_agent" and not business_agent_id:
            raise AdsApiError("mode business_agent requires business_agent_id.")
        if product_feed_id is not None:
            body["product_feed_id"] = product_feed_id
        if business_agent_id is not None:
            body["business_agent_id"] = business_agent_id
        parsed_targeting = object_dict(targeting, "targeting")
        if parsed_targeting is not None:
            body["targeting"] = parsed_targeting
        if objective is not None:
            body["objective"] = objective
        if billing_event_type is not None:
            body["billing_event_type"] = billing_event_type
        landing = query_template(query_string_template)
        if landing is not None:
            body["landing_page_configuration"] = landing
        created = await client.create_campaign(body, idempotency_key=optional_idempotency_key(idempotency_key))
        return _created(created)

    @mcp.tool(annotations=_CREATE)
    async def create_ad_group(
        campaign_id: str,
        name: str,
        billing_event_type: Literal["impression", "click"],
        max_bid_micros: int | None = None,
        strategy: Literal["fixed_bid", "maximize_clicks", "maximize_conversions"] | None = None,
        description: str | None = None,
        context_hints: list[str] | None = None,
        custom_audience_bid_multipliers: list[dict[str, Any]] | None = None,
        product_set: dict[str, Any] | None = None,
        query_string_template: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Create a paused ad group (POST /ad_groups).

        status is always paused. billing_event_type is impression for impression
        campaigns and click for click or conversion campaigns. fixed_bid requires
        max_bid_micros (minimum 1). Omit strategy and max_bid_micros to select
        AutoBid. Do not send max_bid_micros with maximize_clicks or
        maximize_conversions. Bid multipliers are 100000 to 10000000 (0.1x to 10x).
        """

        bid = positive_micros(max_bid_micros, "max_bid_micros", minimum=1)
        if strategy in ("maximize_clicks", "maximize_conversions") and bid is not None:
            raise AdsApiError(
                "max_bid_micros is not a supported adjustment for maximize_clicks or maximize_conversions."
            )
        if strategy == "fixed_bid" and bid is None:
            raise AdsApiError("strategy fixed_bid requires max_bid_micros.")
        bidding: dict[str, Any] = {"billing_event_type": billing_event_type}
        if strategy is not None:
            bidding["strategy"] = strategy
        if bid is not None:
            bidding["max_bid_micros"] = bid
        multipliers = bid_multipliers(custom_audience_bid_multipliers)
        if multipliers is not None:
            bidding["custom_audience_bid_multipliers"] = multipliers
        body: dict[str, Any] = {
            "campaign_id": resource_id(campaign_id, "campaign_id"),
            "name": resource_name(name),
            "status": "paused",
            "bidding_config": bidding,
        }
        if description is not None:
            body["description"] = description
        hints = string_list(context_hints, "context_hints")
        if hints is not None:
            body["context_hints"] = hints
        parsed_set = object_dict(product_set, "product_set")
        if parsed_set is not None:
            body["product_set"] = parsed_set
        landing = query_template(query_string_template)
        if landing is not None:
            body["landing_page_configuration"] = landing
        created = await client.create_ad_group(body, idempotency_key=optional_idempotency_key(idempotency_key))
        return _created(created)

    @mcp.tool(annotations=_CREATE)
    async def create_ad(
        ad_group_id: str,
        name: str,
        creative_type: Literal["chat_card", "product_ad_template"],
        title: str,
        body: str,
        target_url: str | None = None,
        file_id: str | None = None,
        price: str | None = None,
        image_crop: dict[str, Any] | None = None,
        query_string_template: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Create a paused ad (POST /ads).

        status is always paused. chat_card requires target_url and file_id from
        upload_ad_image. product_ad_template takes its image and URL from the
        product feed. title is 3 to 50 characters. body is at most 100 characters.
        image_crop is an optional normalized crop (x, y, width, height from 0 to 1)
        for chat_card creatives that already have file_id.
        """

        creative = _creative(
            creative_type=creative_type,
            title=title,
            body=body,
            target_url=target_url,
            file_id=file_id,
            price=price,
            crop=image_crop,
            title_min=3,
            require_chat_card_assets=True,
        )
        payload: dict[str, Any] = {
            "ad_group_id": resource_id(ad_group_id, "ad_group_id"),
            "name": resource_name(name),
            "status": "paused",
            "creative": creative,
        }
        landing = query_template(query_string_template)
        if landing is not None:
            payload["landing_page_configuration"] = landing
        created = await client.create_ad(payload, idempotency_key=optional_idempotency_key(idempotency_key))
        return _created(created)

    @mcp.tool(annotations=_STATE)
    async def pause_campaign(campaign_id: str) -> dict[str, Any]:
        """Pause a campaign (POST /campaigns/{campaign_id}/pause)."""

        return await client.change_state("campaigns", campaign_id, "pause")

    @mcp.tool(annotations=_STATE)
    async def pause_ad_group(ad_group_id: str) -> dict[str, Any]:
        """Pause an ad group (POST /ad_groups/{ad_group_id}/pause)."""

        return await client.change_state("ad_groups", ad_group_id, "pause")

    @mcp.tool(annotations=_STATE)
    async def pause_ad(ad_id: str) -> dict[str, Any]:
        """Pause an ad (POST /ads/{ad_id}/pause)."""

        return await client.change_state("ads", ad_id, "pause")

    @mcp.tool(annotations=_STATE)
    async def activate_campaign(campaign_id: str) -> dict[str, Any]:
        """Resume a campaign (POST /campaigns/{campaign_id}/activate)."""

        return await client.change_state("campaigns", campaign_id, "activate")

    @mcp.tool(annotations=_STATE)
    async def activate_ad_group(ad_group_id: str) -> dict[str, Any]:
        """Resume an ad group (POST /ad_groups/{ad_group_id}/activate)."""

        return await client.change_state("ad_groups", ad_group_id, "activate")

    @mcp.tool(annotations=_STATE)
    async def activate_ad(ad_id: str) -> dict[str, Any]:
        """Resume an ad (POST /ads/{ad_id}/activate)."""

        return await client.change_state("ads", ad_id, "activate")

    @mcp.tool(annotations=_UPDATE)
    async def update_campaign(
        campaign_id: str,
        name: str | None = None,
        description: str | None = None,
        start_time: int | None = None,
        end_time: int | None = None,
        status: Literal["active", "paused", "archived"] | None = None,
        confirm: bool = False,
        lifetime_spend_limit_micros: int | None = None,
        daily_spend_limit_micros: int | None = None,
        targeting: dict[str, Any] | None = None,
        conversion_event_setting_ids: list[str] | None = None,
        query_string_template: str | None = None,
    ) -> dict[str, Any]:
        """Edit a campaign (POST /campaigns/{campaign_id}).

        Omitted fields stay unchanged. bidding_type cannot be changed. If you
        send a budget, it replaces the budget object, so include every limit
        that should remain. status archived is irreversible and requires
        confirm=true. Use pause_campaign or activate_campaign for those states
        when you do not need to change other fields.
        """

        body: dict[str, Any] = {}
        if name is not None:
            body["name"] = resource_name(name)
        if description is not None:
            body["description"] = description
        start = unix_time(start_time, "start_time")
        end = unix_time(end_time, "end_time")
        if start is not None:
            body["start_time"] = start
        if end is not None:
            body["end_time"] = end
        parsed_status = editable_status(status, confirm=confirm)
        if parsed_status is not None:
            body["status"] = parsed_status
        if lifetime_spend_limit_micros is not None or daily_spend_limit_micros is not None:
            body["budget"] = campaign_budget(lifetime_spend_limit_micros, daily_spend_limit_micros)
        parsed_targeting = object_dict(targeting, "targeting")
        if parsed_targeting is not None:
            body["targeting"] = parsed_targeting
        events = string_list(conversion_event_setting_ids, "conversion_event_setting_ids")
        if events is not None:
            body["conversion_event_setting_ids"] = events
        landing = query_template(query_string_template)
        if landing is not None:
            body["landing_page_configuration"] = landing
        _require_changes(body)
        return await client.update_campaign(campaign_id, body)

    @mcp.tool(annotations=_UPDATE)
    async def update_ad_group(
        ad_group_id: str,
        name: str | None = None,
        description: str | None = None,
        context_hints: list[str] | None = None,
        status: Literal["active", "paused", "archived"] | None = None,
        confirm: bool = False,
        billing_event_type: Literal["impression", "click"] | None = None,
        max_bid_micros: int | None = None,
        strategy: Literal["fixed_bid", "maximize_clicks", "maximize_conversions"] | None = None,
        custom_audience_bid_multipliers: list[dict[str, Any]] | None = None,
        product_set: dict[str, Any] | None = None,
        query_string_template: str | None = None,
    ) -> dict[str, Any]:
        """Edit an ad group (POST /ad_groups/{ad_group_id}).

        If you send bidding fields, billing_event_type is required and the
        bidding_config object replaces the existing one. status archived
        requires confirm=true.
        """

        body: dict[str, Any] = {}
        if name is not None:
            body["name"] = resource_name(name)
        if description is not None:
            body["description"] = description
        hints = string_list(context_hints, "context_hints")
        if hints is not None:
            body["context_hints"] = hints
        parsed_status = editable_status(status, confirm=confirm)
        if parsed_status is not None:
            body["status"] = parsed_status
        bidding_requested = any(
            value is not None
            for value in (
                billing_event_type,
                max_bid_micros,
                strategy,
                custom_audience_bid_multipliers,
            )
        )
        if bidding_requested:
            if billing_event_type is None:
                raise AdsApiError(
                    "Updating bidding_config requires billing_event_type. Send the full bidding config."
                )
            bid = positive_micros(max_bid_micros, "max_bid_micros", minimum=1)
            if strategy in ("maximize_clicks", "maximize_conversions") and bid is not None:
                raise AdsApiError(
                    "max_bid_micros is not a supported adjustment for maximize_clicks or maximize_conversions."
                )
            if strategy == "fixed_bid" and bid is None:
                raise AdsApiError("strategy fixed_bid requires max_bid_micros.")
            bidding: dict[str, Any] = {"billing_event_type": billing_event_type}
            if strategy is not None:
                bidding["strategy"] = strategy
            if bid is not None:
                bidding["max_bid_micros"] = bid
            multipliers = bid_multipliers(custom_audience_bid_multipliers)
            if multipliers is not None:
                bidding["custom_audience_bid_multipliers"] = multipliers
            body["bidding_config"] = bidding
        parsed_set = object_dict(product_set, "product_set")
        if parsed_set is not None:
            body["product_set"] = parsed_set
        landing = query_template(query_string_template)
        if landing is not None:
            body["landing_page_configuration"] = landing
        _require_changes(body)
        return await client.update_ad_group(ad_group_id, body)

    @mcp.tool(annotations=_UPDATE)
    async def update_ad(
        ad_id: str,
        name: str | None = None,
        status: Literal["active", "paused", "archived"] | None = None,
        confirm: bool = False,
        creative_type: Literal["chat_card", "product_ad_template"] | None = None,
        title: str | None = None,
        body: str | None = None,
        target_url: str | None = None,
        file_id: str | None = None,
        price: str | None = None,
        image_crop: dict[str, Any] | None = None,
        query_string_template: str | None = None,
    ) -> dict[str, Any]:
        """Edit an ad (POST /ads/{ad_id}).

        If you include a creative, send the full creative: type, title, and body
        are required, and a chat_card still needs target_url and file_id.
        Editing creative starts a new review. status archived requires confirm=true.
        """

        payload: dict[str, Any] = {}
        if name is not None:
            payload["name"] = resource_name(name)
        parsed_status = editable_status(status, confirm=confirm)
        if parsed_status is not None:
            payload["status"] = parsed_status
        creative_requested = any(
            value is not None for value in (creative_type, title, body, target_url, file_id, price, image_crop)
        )
        if creative_requested:
            if creative_type is None or title is None or body is None:
                raise AdsApiError("Updating creative requires creative_type, title, and body.")
            payload["creative"] = _creative(
                creative_type=creative_type,
                title=title,
                body=body,
                target_url=target_url,
                file_id=file_id,
                price=price,
                crop=image_crop,
                title_min=1,
                require_chat_card_assets=True,
            )
        landing = query_template(query_string_template)
        if landing is not None:
            payload["landing_page_configuration"] = landing
        _require_changes(payload)
        return await client.update_ad(ad_id, payload)


def _creative(
    *,
    creative_type: str,
    title: str,
    body: str,
    target_url: str | None,
    file_id: str | None,
    price: str | None,
    crop: dict[str, Any] | None,
    title_min: int,
    require_chat_card_assets: bool,
) -> dict[str, Any]:
    if not isinstance(title, str) or not (title_min <= len(title) <= 50) or not any(not char.isspace() for char in title):
        raise AdsApiError(f"title must be {title_min} to 50 characters and include a non-space character.")
    if not isinstance(body, str) or len(body) > 100:
        raise AdsApiError("body must be a string of at most 100 characters.")
    creative: dict[str, Any] = {"type": creative_type, "title": title, "body": body}
    if price is not None:
        if not isinstance(price, str) or len(price) > 100:
            raise AdsApiError("price must be a string of at most 100 characters.")
        creative["price"] = price
    if creative_type == "chat_card" and require_chat_card_assets:
        if not target_url or not file_id:
            raise AdsApiError("chat_card creatives require target_url and file_id.")
    if target_url is not None:
        creative["target_url"] = http_url(target_url, "target_url", max_length=2048)
    if file_id is not None:
        if not isinstance(file_id, str) or not file_id.strip():
            raise AdsApiError("file_id must be a non-empty string.")
        creative["file_id"] = file_id
    parsed_crop = image_crop(crop)
    if parsed_crop is not None:
        if creative_type != "chat_card" or not file_id:
            raise AdsApiError("image_crop is only supported on a chat_card creative that has file_id.")
        creative["image_crop"] = parsed_crop
    return creative


def _created(resource: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {"resource": resource}
    if resource.get("status") == "paused":
        payload["note"] = _PAUSED_NOTE
    return payload


def _require_changes(body: dict[str, Any]) -> None:
    if not body:
        raise AdsApiError("Provide at least one field to update.")
