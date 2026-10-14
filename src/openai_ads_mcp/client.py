"""HTTP client for the OpenAI Ads Advertiser API.

Request paths, query names, and bodies follow the published API reference and
OpenAPI spec at https://developers.openai.com/ads. Array query parameters use
the bracket form shown in the official examples (``fields[]``, ``include[]``,
``time_ranges[]``).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import quote

import httpx

from openai_ads_mcp.errors import AdsApiError, redact
from openai_ads_mcp.rate_limit import SlidingWindowLimiter

logger = logging.getLogger("openai_ads_mcp.client")

# httpx logs request headers at DEBUG, which would include the Ads API key.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

_STATUS_HINTS = {
    400: "Validation failed. Check required fields, allowed values, amounts, and parent IDs.",
    401: "Authentication failed. Check that OPENAI_ADS_API_KEY is an Ads API bearer token.",
    403: "Access denied. The key may not be allowed to use this account or feature.",
    404: "Resource not found. Check the ID and that the key belongs to this ad account.",
    409: "Conflict. An idempotency key may have been reused with a different body, or a revision is stale.",
    413: "The request is too large for this endpoint.",
    422: "The API rejected the values. Check amounts, dates, and incompatible settings.",
    429: "Rate limited. Retries with backoff were exhausted. Wait before calling this endpoint again.",
}

_HIERARCHY = ("ad_account", "campaign", "ad_group", "ad")
_METRICS = ("impressions", "clicks", "spend", "ctr", "cpc")


class AdsClient:
    """Async client with pagination, per-endpoint throttling, and 429 backoff."""

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = "https://api.ads.openai.com/v1",
        timeout: float = 30.0,
        max_retries: int = 5,
        retry_base_seconds: float = 1.0,
        retry_max_seconds: float = 30.0,
        endpoint_rate_limit: int = 600,
        global_rate_limit: int = 1200,
        rate_window_seconds: float = 60.0,
        max_pages: int = 25,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Callable[[], float] | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        self._api_key = api_key
        # Keep a trailing slash so relative paths stay under /v1.
        # A leading slash would replace the base path and drop /v1.
        self._base_url = base_url.rstrip("/") + "/"
        self._max_retries = max_retries
        self._retry_base_seconds = retry_base_seconds
        self._retry_max_seconds = retry_max_seconds
        self._max_pages = max_pages
        self._sleep = sleep
        self._endpoint_limiter = SlidingWindowLimiter(
            endpoint_rate_limit,
            rate_window_seconds,
            clock=clock,
            sleep=sleep,
        )
        self._global_limiter = SlidingWindowLimiter(
            global_rate_limit,
            rate_window_seconds,
            clock=clock,
            sleep=sleep,
        )
        self._http = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=httpx.Timeout(timeout),
            transport=transport,
            follow_redirects=False,
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def get_ad_account(self) -> dict[str, Any]:
        """GET /ad_account."""

        return await self._get_object("/ad_account", endpoint_key="GET /ad_account")

    async def list_campaigns(
        self,
        *,
        limit: int | None = None,
        after: str | None = None,
        before: str | None = None,
        order: str | None = None,
        name: str | None = None,
        include_serving_issues: bool = False,
        fetch_all: bool = True,
    ) -> dict[str, Any]:
        """GET /campaigns, following ``has_more`` when ``fetch_all`` is true."""

        params = _list_params(
            limit=limit,
            after=after,
            before=before,
            order=order,
            name=name,
            include_serving_issues=include_serving_issues,
        )
        return await self._get_pages("/campaigns", params, "GET /campaigns", fetch_all=fetch_all)

    async def list_ad_groups(
        self,
        campaign_id: str,
        *,
        limit: int | None = None,
        after: str | None = None,
        before: str | None = None,
        order: str | None = None,
        name: str | None = None,
        include_serving_issues: bool = False,
        fetch_all: bool = True,
    ) -> dict[str, Any]:
        """GET /ad_groups?campaign_id=..."""

        params = _list_params(
            limit=limit,
            after=after,
            before=before,
            order=order,
            name=name,
            include_serving_issues=include_serving_issues,
        )
        params["campaign_id"] = _resource_id(campaign_id, "campaign_id")
        return await self._get_pages("/ad_groups", params, "GET /ad_groups", fetch_all=fetch_all)

    async def list_ads(
        self,
        ad_group_id: str,
        *,
        limit: int | None = None,
        after: str | None = None,
        before: str | None = None,
        order: str | None = None,
        name: str | None = None,
        include_serving_issues: bool = False,
        fetch_all: bool = True,
    ) -> dict[str, Any]:
        """GET /ads?ad_group_id=..."""

        params = _list_params(
            limit=limit,
            after=after,
            before=before,
            order=order,
            name=name,
            include_serving_issues=include_serving_issues,
        )
        params["ad_group_id"] = _resource_id(ad_group_id, "ad_group_id")
        return await self._get_pages("/ads", params, "GET /ads", fetch_all=fetch_all)

    async def get_campaign(self, campaign_id: str, *, include_serving_issues: bool = False) -> dict[str, Any]:
        """GET /campaigns/{campaign_id}."""

        return await self._get_object(
            f"/campaigns/{_quote_id(campaign_id, 'campaign_id')}",
            endpoint_key="GET /campaigns/{campaign_id}",
            params=_include_param(include_serving_issues),
        )

    async def get_ad_group(self, ad_group_id: str, *, include_serving_issues: bool = False) -> dict[str, Any]:
        """GET /ad_groups/{ad_group_id}."""

        return await self._get_object(
            f"/ad_groups/{_quote_id(ad_group_id, 'ad_group_id')}",
            endpoint_key="GET /ad_groups/{ad_group_id}",
            params=_include_param(include_serving_issues),
        )

    async def get_ad(self, ad_id: str, *, include_serving_issues: bool = False) -> dict[str, Any]:
        """GET /ads/{ad_id}."""

        return await self._get_object(
            f"/ads/{_quote_id(ad_id, 'ad_id')}",
            endpoint_key="GET /ads/{ad_id}",
            params=_include_param(include_serving_issues),
        )

    async def get_insights(
        self,
        *,
        level: str,
        start_date: str,
        end_date: str,
        campaign_id: str | None = None,
        ad_group_id: str | None = None,
        ad_id: str | None = None,
        time_granularity: str = "daily",
        aggregation_level: str | None = None,
        timezone_name: str | None = None,
        limit: int | None = None,
        fetch_all: bool = True,
    ) -> dict[str, Any]:
        """GET the insights endpoint for an account, campaign, ad group, or ad.

        ``start_date`` and ``end_date`` are account-local ``YYYY-MM-DD`` values.
        ``end_date`` is inclusive, matching the ``date_range`` time range.
        Requested metrics are impressions, clicks, spend, CTR, and CPC.
        """

        if level not in _HIERARCHY:
            raise AdsApiError("level must be ad_account, campaign, ad_group, or ad.")
        if time_granularity not in ("hourly", "daily", "monthly", "none"):
            raise AdsApiError("time_granularity must be hourly, daily, monthly, or none.")
        aggregation = aggregation_level or level
        if aggregation not in _HIERARCHY:
            raise AdsApiError("aggregation_level must be ad_account, campaign, ad_group, or ad.")
        if _HIERARCHY.index(aggregation) < _HIERARCHY.index(level):
            raise AdsApiError(
                f"aggregation_level {aggregation} is above the {level} endpoint. "
                "Each insights endpoint only returns its own level and levels below it."
            )
        since = _calendar_date(start_date, "start_date")
        until = _calendar_date(end_date, "end_date")
        if until < since:
            raise AdsApiError("end_date must be on or after start_date.")
        if limit is not None and not (1 <= limit <= 2000):
            raise AdsApiError("insights limit must be between 1 and 2000.")

        time_range: dict[str, str] = {"type": "date_range", "since": since, "until": until}
        if timezone_name:
            time_range["timezone"] = timezone_name
        fields = [
            "metadata.readable_time",
            f"{aggregation}.id",
            f"{aggregation}.name",
            *[f"{aggregation}.{metric}" for metric in _METRICS],
        ]
        params: dict[str, Any] = {
            "time_granularity": time_granularity,
            "aggregation_level": aggregation,
            "time_ranges[]": json.dumps(time_range, separators=(",", ":")),
            "fields[]": fields,
        }
        if limit is not None:
            params["limit"] = limit

        if level == "ad_account":
            path = "/ad_account/insights"
            endpoint_key = "GET /ad_account/insights"
        elif level == "campaign":
            path = f"/campaigns/{_quote_id(campaign_id or '', 'campaign_id')}/insights"
            endpoint_key = "GET /campaigns/{campaign_id}/insights"
        elif level == "ad_group":
            path = f"/ad_groups/{_quote_id(ad_group_id or '', 'ad_group_id')}/insights"
            endpoint_key = "GET /ad_groups/{ad_group_id}/insights"
        else:
            path = f"/ads/{_quote_id(ad_id or '', 'ad_id')}/insights"
            endpoint_key = "GET /ads/{ad_id}/insights"

        page = await self._get_pages(path, params, endpoint_key, fetch_all=fetch_all)
        page["level"] = level
        page["aggregation_level"] = aggregation
        page["start_date"] = since
        page["end_date"] = until
        page["metrics"] = list(_METRICS)
        return page

    async def upload_image(self, image_url: str) -> dict[str, Any]:
        """POST /upload with a remote image URL. Returns ``file_id``."""

        body = await self._request(
            "POST",
            "/upload",
            endpoint_key="POST /upload",
            json_body={"image_url": image_url},
        )
        if not isinstance(body, dict) or not isinstance(body.get("file_id"), str):
            raise AdsApiError("POST /upload did not return a file_id.")
        return body

    async def create_campaign(self, body: Mapping[str, Any], *, idempotency_key: str) -> dict[str, Any]:
        """POST /campaigns."""

        return await self._post_object("/campaigns", "POST /campaigns", body, idempotency_key=idempotency_key)

    async def create_ad_group(self, body: Mapping[str, Any], *, idempotency_key: str) -> dict[str, Any]:
        """POST /ad_groups."""

        return await self._post_object("/ad_groups", "POST /ad_groups", body, idempotency_key=idempotency_key)

    async def create_ad(self, body: Mapping[str, Any], *, idempotency_key: str) -> dict[str, Any]:
        """POST /ads."""

        return await self._post_object("/ads", "POST /ads", body, idempotency_key=idempotency_key)

    async def update_campaign(self, campaign_id: str, body: Mapping[str, Any]) -> dict[str, Any]:
        """POST /campaigns/{campaign_id}."""

        path = f"/campaigns/{_quote_id(campaign_id, 'campaign_id')}"
        return await self._post_object(path, "POST /campaigns/{campaign_id}", body)

    async def update_ad_group(self, ad_group_id: str, body: Mapping[str, Any]) -> dict[str, Any]:
        """POST /ad_groups/{ad_group_id}."""

        path = f"/ad_groups/{_quote_id(ad_group_id, 'ad_group_id')}"
        return await self._post_object(path, "POST /ad_groups/{ad_group_id}", body)

    async def update_ad(self, ad_id: str, body: Mapping[str, Any]) -> dict[str, Any]:
        """POST /ads/{ad_id}."""

        path = f"/ads/{_quote_id(ad_id, 'ad_id')}"
        return await self._post_object(path, "POST /ads/{ad_id}", body)

    async def change_state(self, kind: str, resource_id: str, action: str) -> dict[str, Any]:
        """POST /{kind}/{id}/activate or /pause."""

        if kind not in ("campaigns", "ad_groups", "ads"):
            raise AdsApiError("kind must be campaigns, ad_groups, or ads.")
        if action not in ("activate", "pause"):
            raise AdsApiError("action must be activate or pause.")
        label = {"campaigns": "campaign_id", "ad_groups": "ad_group_id", "ads": "ad_id"}[kind]
        path = f"/{kind}/{_quote_id(resource_id, label)}/{action}"
        endpoint_key = f"POST /{kind}/{{{label}}}/{action}"
        return await self._post_object(path, endpoint_key, None)

    async def _get_object(
        self,
        path: str,
        *,
        endpoint_key: str,
        params: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        body = await self._request("GET", path, endpoint_key=endpoint_key, params=params)
        if not isinstance(body, dict):
            raise AdsApiError("The Ads API returned a response that was not a JSON object.")
        return body

    async def _post_object(
        self,
        path: str,
        endpoint_key: str,
        body: Mapping[str, Any] | None,
        *,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        payload = await self._request(
            "POST",
            path,
            endpoint_key=endpoint_key,
            json_body=None if body is None else dict(body),
            idempotency_key=idempotency_key,
        )
        if not isinstance(payload, dict):
            raise AdsApiError("The Ads API returned a response that was not a JSON object.")
        return payload

    async def _get_pages(
        self,
        path: str,
        params: Mapping[str, Any],
        endpoint_key: str,
        *,
        fetch_all: bool,
    ) -> dict[str, Any]:
        page_params = {key: value for key, value in params.items() if value is not None}
        if page_params.get("after") and page_params.get("before"):
            raise AdsApiError("Send only one pagination cursor: after or before.")
        # A backward cursor is a single page. Forward pagination uses after=last_id.
        follow = fetch_all and not page_params.get("before")
        pages: list[dict[str, Any]] = []
        seen_cursors: set[str] = set()
        max_pages = self._max_pages if follow else 1
        note: str | None = None
        for _ in range(max_pages):
            body = await self._request("GET", path, endpoint_key=endpoint_key, params=page_params)
            if not isinstance(body, dict):
                raise AdsApiError("The Ads API returned a page that was not a JSON object.")
            pages.append(body)
            if not follow or not body.get("has_more"):
                break
            cursor = body.get("last_id")
            if not isinstance(cursor, str) or cursor == "" or cursor in seen_cursors:
                note = "Stopped pagination because the page set has_more without a new last_id cursor."
                break
            seen_cursors.add(cursor)
            page_params.pop("before", None)
            page_params["after"] = cursor
        else:
            if follow and pages and pages[-1].get("has_more"):
                note = (
                    f"Stopped after {max_pages} pages. Pass after={pages[-1].get('last_id')!s} to continue."
                )

        first = pages[0]
        last = pages[-1]
        rows: list[Any] = []
        for page in pages:
            chunk = page.get("data")
            if isinstance(chunk, list):
                rows.extend(chunk)
        merged = {
            key: value
            for key, value in first.items()
            if key not in {"data", "has_more", "first_id", "last_id"}
        }
        merged.update(
            {
                "object": first.get("object", "list"),
                "data": rows,
                "has_more": bool(last.get("has_more")),
                "first_id": first.get("first_id"),
                "last_id": last.get("last_id"),
                "pages_fetched": len(pages),
                "truncated": bool(follow and last.get("has_more")),
            }
        )
        if note:
            merged["pagination_note"] = note
        return merged

    async def _request(
        self,
        method: str,
        path: str,
        *,
        endpoint_key: str,
        params: Mapping[str, Any] | None = None,
        json_body: Mapping[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> Any:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Accept": "application/json",
        }
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        request_params = None if params is None else dict(params)
        attempt = 0
        while True:
            await self._global_limiter.acquire("__global__")
            await self._endpoint_limiter.acquire(endpoint_key)
            try:
                response = await self._http.request(
                    method,
                    path.lstrip("/"),
                    params=request_params,
                    json=None if json_body is None else dict(json_body),
                    headers=headers,
                )
            except httpx.TimeoutException as exc:
                raise AdsApiError("The OpenAI Ads API request timed out.") from exc
            except httpx.RequestError as exc:
                raise AdsApiError("Could not reach the OpenAI Ads API.") from exc

            if response.status_code != 429 or attempt >= self._max_retries:
                return self._parse_response(response, method, path)

            delay = _retry_delay(
                response,
                attempt,
                base=self._retry_base_seconds,
                cap=self._retry_max_seconds,
            )
            logger.warning(
                "Ads API rate limited %s %s; retrying in %.2fs (attempt %s of %s).",
                method,
                path,
                delay,
                attempt + 1,
                self._max_retries,
            )
            sleeper = self._sleep or _default_sleep
            await sleeper(delay)
            attempt += 1

    def _parse_response(self, response: httpx.Response, method: str, path: str) -> Any:
        status = response.status_code
        if 300 <= status < 400:
            logger.info("Ads API %s %s -> %s", method, path, status)
            raise AdsApiError(
                f"OpenAI Ads API returned redirect {status}. This server does not follow redirects."
            )
        if status >= 400:
            logger.info("Ads API %s %s -> %s", method, path, status)
            raise AdsApiError(_error_message(response, secrets=(self._api_key,)))
        logger.info("Ads API %s %s -> %s", method, path, status)
        if not response.content:
            raise AdsApiError("The OpenAI Ads API returned an empty body.")
        try:
            return response.json()
        except json.JSONDecodeError as exc:
            raise AdsApiError("The OpenAI Ads API returned a body that was not JSON.") from exc


def _error_message(response: httpx.Response, *, secrets: tuple[str, ...]) -> str:
    message = ""
    code = ""
    try:
        payload = response.json()
    except json.JSONDecodeError:
        payload = None
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            message = _text(error.get("message")) or _text(error.get("detail"))
            code = _text(error.get("code")) or _text(error.get("type"))
        elif isinstance(error, str):
            message = error
        if not message:
            message = _text(payload.get("message")) or _text(payload.get("detail"))
    if not message:
        message = response.text.strip()[:500] or "The Ads API returned an empty error body."
    hint = _STATUS_HINTS.get(response.status_code, "The Ads API rejected the request.")
    prefix = f"OpenAI Ads API error {response.status_code}"
    if code:
        prefix = f"{prefix} ({code})"
    return redact(f"{prefix}: {message} {hint}", secrets)


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _retry_delay(response: httpx.Response, attempt: int, *, base: float, cap: float) -> float:
    header = response.headers.get("retry-after")
    if header:
        parsed = _parse_retry_after(header)
        if parsed is not None:
            return min(cap, max(0.0, parsed))
    try:
        payload = response.json()
    except json.JSONDecodeError:
        payload = None
    if isinstance(payload, dict):
        for candidate in _retry_candidates(payload):
            return min(cap, max(0.0, float(candidate)))
    return min(cap, base * (2**attempt))


def _retry_candidates(payload: Mapping[str, Any]) -> list[float]:
    found: list[float] = []
    for key in ("retry_after_seconds", "retry_after"):
        value = payload.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            found.append(float(value))
    error = payload.get("error")
    if isinstance(error, dict):
        for key in ("retry_after_seconds", "retry_after"):
            value = error.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                found.append(float(value))
    return found


def _parse_retry_after(header: str) -> float | None:
    try:
        return float(header)
    except ValueError:
        parsed = parsedate_to_datetime(header)
        if parsed is None:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return (parsed - datetime.now(timezone.utc)).total_seconds()


def _list_params(
    *,
    limit: int | None,
    after: str | None,
    before: str | None,
    order: str | None,
    name: str | None,
    include_serving_issues: bool,
) -> dict[str, Any]:
    if limit is not None and not (1 <= limit <= 500):
        raise AdsApiError("limit must be between 1 and 500.")
    if order is not None and order not in ("asc", "desc"):
        raise AdsApiError("order must be asc or desc.")
    params: dict[str, Any] = {}
    if limit is not None:
        params["limit"] = limit
    if after:
        params["after"] = after
    if before:
        params["before"] = before
    if order:
        params["order"] = order
    if name is not None:
        if not (3 <= len(name) <= 1000) or not any(not char.isspace() for char in name):
            raise AdsApiError("name must be 3 to 1000 characters and include a non-space character.")
        params["name"] = name
    if include_serving_issues:
        params["include[]"] = "serving_issues"
    return params


def _include_param(include_serving_issues: bool) -> dict[str, str] | None:
    if not include_serving_issues:
        return None
    return {"include[]": "serving_issues"}


def _resource_id(value: str, label: str) -> str:
    _quote_id(value, label)
    return value


def _quote_id(value: str, label: str) -> str:
    if not isinstance(value, str) or value.strip() == "" or value != value.strip():
        raise AdsApiError(f"{label} must be a non-empty ID.")
    return quote(value, safe="")


def _calendar_date(value: str, label: str) -> str:
    if not isinstance(value, str):
        raise AdsApiError(f"{label} must be a YYYY-MM-DD date.")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise AdsApiError(f"{label} must be a YYYY-MM-DD date.") from exc
    return parsed.date().isoformat()


async def _default_sleep(seconds: float) -> None:
    import asyncio

    await asyncio.sleep(seconds)
