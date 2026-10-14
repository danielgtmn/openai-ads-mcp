"""MCP tool registration."""

from mcp.server.fastmcp import FastMCP

from openai_ads_mcp.client import AdsClient
from openai_ads_mcp.tools.read import register_read_tools
from openai_ads_mcp.tools.write import register_write_tools


def register_tools(mcp: FastMCP, client: AdsClient, *, read_only: bool) -> None:
    """Register read tools, and write tools only when the server is not read-only."""

    register_read_tools(mcp, client)
    if not read_only:
        register_write_tools(mcp, client)
