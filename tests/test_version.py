"""Release metadata stays in sync."""

import tomllib
from pathlib import Path

from openai_ads_mcp import __version__


def test_version_matches_pyproject_and_changelog() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    changelog = Path("CHANGELOG.md").read_text(encoding="utf-8")
    assert pyproject["project"]["version"] == __version__ == "0.1.0"
    assert "## 0.1.0" in changelog


def test_compose_does_not_publish_host_ports() -> None:
    text = Path("docker-compose.yml").read_text(encoding="utf-8")
    assert "\nports:" not in text
    assert "expose:" in text
    assert "MCP_READ_ONLY" in text
    assert "/health" in text
