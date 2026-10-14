"""Environment configuration.

Write tools are registered only when ``MCP_READ_ONLY`` is exactly ``false``
(case-insensitive, surrounding whitespace ignored). Every other value,
including an unset variable, keeps the server read-only.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

from openai_ads_mcp.errors import ConfigError

DEFAULT_BASE_URL = "https://api.ads.openai.com/v1"
LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


def _mapping(source: Mapping[str, str] | None) -> Mapping[str, str]:
    if source is None:
        return os.environ
    return source


def _optional(env: Mapping[str, str], name: str) -> str | None:
    if name not in env:
        return None
    return env[name]


def _secret(env: Mapping[str, str], name: str) -> str:
    value = _optional(env, name)
    if value is None or value.strip() == "":
        raise ConfigError(f"{name} is required.")
    if value != value.strip() or any(char in value for char in "\r\n"):
        raise ConfigError(f"{name} must not contain surrounding whitespace or newlines.")
    try:
        value.encode("ascii")
    except UnicodeEncodeError as exc:
        raise ConfigError(f"{name} must be ASCII.") from exc
    return value


def _int(env: Mapping[str, str], name: str, default: int, *, minimum: int) -> int:
    raw = _optional(env, name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer.") from exc
    if value < minimum:
        raise ConfigError(f"{name} must be at least {minimum}.")
    return value


def _float(env: Mapping[str, str], name: str, default: float, *, minimum: float) -> float:
    raw = _optional(env, name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a number.") from exc
    if value < minimum:
        raise ConfigError(f"{name} must be at least {minimum}.")
    return value


def read_only_enabled(raw: str | None) -> bool:
    """Return False only when the operator explicitly opts into writes."""

    if raw is None:
        return True
    return raw.strip().lower() != "false"


@dataclass(frozen=True)
class Settings:
    """Runtime settings loaded from the environment."""

    openai_ads_api_key: str
    mcp_auth_token: str
    read_only: bool
    host: str
    port: int
    base_url: str
    log_level: str
    endpoint_rate_limit: int
    global_rate_limit: int
    rate_window_seconds: float
    max_retries: int
    retry_base_seconds: float
    retry_max_seconds: float
    request_timeout_seconds: float
    max_pages: int

    @classmethod
    def from_env(cls, source: Mapping[str, str] | None = None) -> Settings:
        env = _mapping(source)
        host = (_optional(env, "HOST") or "0.0.0.0").strip() or "0.0.0.0"
        base_url = (_optional(env, "OPENAI_ADS_BASE_URL") or DEFAULT_BASE_URL).strip()
        if not base_url:
            raise ConfigError("OPENAI_ADS_BASE_URL must not be empty.")
        log_level = (_optional(env, "LOG_LEVEL") or "INFO").strip().upper()
        if log_level not in LOG_LEVELS:
            allowed = ", ".join(LOG_LEVELS)
            raise ConfigError(f"LOG_LEVEL must be one of: {allowed}.")
        port = _int(env, "PORT", 8000, minimum=1)
        if port > 65535:
            raise ConfigError("PORT must be between 1 and 65535.")
        return cls(
            openai_ads_api_key=_secret(env, "OPENAI_ADS_API_KEY"),
            mcp_auth_token=_secret(env, "MCP_AUTH_TOKEN"),
            read_only=read_only_enabled(_optional(env, "MCP_READ_ONLY")),
            host=host,
            port=port,
            base_url=base_url.rstrip("/"),
            log_level=log_level,
            endpoint_rate_limit=_int(env, "ADS_ENDPOINT_RATE_LIMIT", 600, minimum=1),
            global_rate_limit=_int(env, "ADS_GLOBAL_RATE_LIMIT", 1200, minimum=1),
            rate_window_seconds=_float(env, "ADS_RATE_WINDOW_SECONDS", 60.0, minimum=0.001),
            max_retries=_int(env, "ADS_MAX_RETRIES", 5, minimum=0),
            retry_base_seconds=_float(env, "ADS_RETRY_BASE_SECONDS", 1.0, minimum=0.0),
            retry_max_seconds=_float(env, "ADS_RETRY_MAX_SECONDS", 30.0, minimum=0.0),
            request_timeout_seconds=_float(env, "ADS_REQUEST_TIMEOUT_SECONDS", 30.0, minimum=0.1),
            max_pages=_int(env, "ADS_MAX_PAGES", 25, minimum=1),
        )
