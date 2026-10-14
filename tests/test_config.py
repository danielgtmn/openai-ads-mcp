"""Configuration parsing."""

import pytest

from openai_ads_mcp.config import Settings, read_only_enabled
from openai_ads_mcp.errors import ConfigError


def _env(**overrides: str) -> dict[str, str]:
    base = {
        "OPENAI_ADS_API_KEY": "ads-test-key",
        "MCP_AUTH_TOKEN": "mcp-test-token",
    }
    base.update(overrides)
    return base


def test_defaults_are_read_only_on_port_8000() -> None:
    settings = Settings.from_env(_env())
    assert settings.read_only is True
    assert settings.port == 8000
    assert settings.host == "0.0.0.0"
    assert settings.base_url == "https://api.ads.openai.com/v1"
    assert settings.endpoint_rate_limit == 600
    assert settings.global_rate_limit == 1200
    assert settings.max_pages == 25


@pytest.mark.parametrize("raw", [None, "", "true", "TRUE", "1", "yes", "no", "0", "falsey"])
def test_only_false_enables_writes(raw: str | None) -> None:
    assert read_only_enabled(raw) is True
    env = _env()
    if raw is not None:
        env["MCP_READ_ONLY"] = raw
    assert Settings.from_env(env).read_only is True


@pytest.mark.parametrize("raw", ["false", "False", " FALSE "])
def test_false_enables_writes(raw: str) -> None:
    assert read_only_enabled(raw) is False
    assert Settings.from_env(_env(MCP_READ_ONLY=raw)).read_only is False


def test_missing_secrets_are_rejected() -> None:
    with pytest.raises(ConfigError, match="OPENAI_ADS_API_KEY"):
        Settings.from_env({"MCP_AUTH_TOKEN": "mcp-test-token"})
    with pytest.raises(ConfigError, match="MCP_AUTH_TOKEN"):
        Settings.from_env({"OPENAI_ADS_API_KEY": "ads-test-key"})


def test_secrets_cannot_contain_newlines() -> None:
    with pytest.raises(ConfigError, match="MCP_AUTH_TOKEN"):
        Settings.from_env(_env(MCP_AUTH_TOKEN="token\nmore"))
