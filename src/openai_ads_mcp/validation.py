"""Local checks for values the Ads API documents as constrained."""

from __future__ import annotations

import uuid
from typing import Any
from urllib.parse import urlsplit

from openai_ads_mcp.errors import AdsApiError

_MIN_UNIX = 946684800
_MAX_UNIX = 4102444800


def resource_id(value: str, label: str) -> str:
    if not isinstance(value, str) or value.strip() == "" or value != value.strip():
        raise AdsApiError(f"{label} must be a non-empty ID.")
    return value


def resource_name(value: str, label: str = "name") -> str:
    if not isinstance(value, str) or not (3 <= len(value) <= 1000) or not any(not char.isspace() for char in value):
        raise AdsApiError(f"{label} must be 3 to 1000 characters and include a non-space character.")
    return value


def optional_idempotency_key(value: str | None) -> str:
    if value is None or value == "":
        return str(uuid.uuid4())
    if not isinstance(value, str) or not (1 <= len(value) <= 255) or not any(not char.isspace() for char in value):
        raise AdsApiError("idempotency_key must be 1 to 255 characters and include a non-space character.")
    return value


def positive_micros(value: int | None, label: str, *, minimum: int) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise AdsApiError(f"{label} must be an integer.")
    if value < minimum:
        raise AdsApiError(f"{label} must be at least {minimum}.")
    return value


def campaign_budget(
    lifetime_spend_limit_micros: int | None,
    daily_spend_limit_micros: int | None,
) -> dict[str, int]:
    lifetime = positive_micros(lifetime_spend_limit_micros, "lifetime_spend_limit_micros", minimum=1_000_000)
    daily = positive_micros(daily_spend_limit_micros, "daily_spend_limit_micros", minimum=1_000_000)
    budget: dict[str, int] = {}
    if lifetime is not None:
        budget["lifetime_spend_limit_micros"] = lifetime
    if daily is not None:
        budget["daily_spend_limit_micros"] = daily
    if not budget:
        raise AdsApiError(
            "Provide lifetime_spend_limit_micros or daily_spend_limit_micros. "
            "Each value is an integer number of micros and the minimum is 1000000."
        )
    return budget


def unix_time(value: int | None, label: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise AdsApiError(f"{label} must be a Unix timestamp in seconds.")
    if not _MIN_UNIX <= value <= _MAX_UNIX:
        raise AdsApiError(f"{label} must be between {_MIN_UNIX} and {_MAX_UNIX}.")
    return value


def http_url(value: str, label: str, *, max_length: int | None = None) -> str:
    if not isinstance(value, str) or value.strip() == "":
        raise AdsApiError(f"{label} must be an absolute http or https URL.")
    if max_length is not None and len(value) > max_length:
        raise AdsApiError(f"{label} must be at most {max_length} characters.")
    parsed = urlsplit(value)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise AdsApiError(f"{label} must be an absolute http or https URL.")
    return value


def object_dict(value: Any, label: str) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise AdsApiError(f"{label} must be an object.")
    return value


def string_list(value: list[str] | None, label: str) -> list[str] | None:
    if value is None:
        return None
    if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
        raise AdsApiError(f"{label} must be a list of non-empty strings.")
    return list(value)


def bid_multipliers(value: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        raise AdsApiError("custom_audience_bid_multipliers must be a list.")
    cleaned: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            raise AdsApiError("Each bid multiplier must be an object.")
        audience_id = item.get("custom_audience_id")
        multiplier = item.get("bid_multiplier_micros")
        if not isinstance(audience_id, str) or not audience_id.strip():
            raise AdsApiError("Each bid multiplier needs custom_audience_id.")
        if isinstance(multiplier, bool) or not isinstance(multiplier, int) or not 100_000 <= multiplier <= 10_000_000:
            raise AdsApiError("bid_multiplier_micros must be an integer from 100000 to 10000000 (0.1x to 10x).")
        cleaned.append(
            {"custom_audience_id": audience_id, "bid_multiplier_micros": multiplier}
        )
    return cleaned


def image_crop(value: dict[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise AdsApiError("image_crop must be an object with x, y, width, and height.")
    cleaned: dict[str, Any] = {}
    for key in ("x", "y", "width", "height"):
        number = value.get(key)
        if isinstance(number, bool) or not isinstance(number, (int, float)):
            raise AdsApiError(f"image_crop.{key} must be a number from 0 to 1.")
        if not 0 <= float(number) <= 1:
            raise AdsApiError(f"image_crop.{key} must be from 0 to 1.")
        cleaned[key] = number
    return cleaned


def query_template(value: str | None) -> dict[str, str] | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > 2048:
        raise AdsApiError("query_string_template must be a string of at most 2048 characters.")
    return {"query_string_template": value}


def editable_status(status: str | None, *, confirm: bool) -> str | None:
    if status is None:
        return None
    if status not in ("active", "paused", "archived"):
        raise AdsApiError("status must be active, paused, or archived.")
    if status == "archived" and not confirm:
        raise AdsApiError(
            "Archiving is irreversible. Pass confirm=true to set status to archived. "
            "This server does not expose a separate archive tool."
        )
    return status
