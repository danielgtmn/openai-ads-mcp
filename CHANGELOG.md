# Changelog

## 0.1.0

- Initial source release of an unofficial Streamable HTTP MCP server for the OpenAI Ads Advertiser API.
- Read tools for the ad account, campaigns, ad groups, ads, status, and insights (impressions, clicks, spend, CTR, CPC).
- Write tools for image upload, paused creates, pause, activate, and edits. Archive is only available through update with `confirm=true`.
- `MCP_READ_ONLY` defaults to true. Write tools are registered only when it is `false`.
- Bearer authentication on `/mcp`, open `GET /health`, pagination, and 429 backoff.
