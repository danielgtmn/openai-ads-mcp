"""Errors that are safe to return to an MCP client."""

from __future__ import annotations

from collections.abc import Iterable


class ConfigError(Exception):
    """The process cannot start because configuration is missing or invalid."""


class AdsApiError(Exception):
    """A failed or rejected call to the OpenAI Ads API, or invalid tool input."""


def redact(text: str, secrets: Iterable[str]) -> str:
    """Remove configured secrets from text that might be logged or returned."""

    redacted = text
    for secret in secrets:
        if secret:
            redacted = redacted.replace(secret, "[redacted]")
    return redacted
