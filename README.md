# OpenAI Ads MCP server

Unofficial [Model Context Protocol](https://modelcontextprotocol.io) server for the [OpenAI Ads Advertiser API](https://developers.openai.com/ads). It is not affiliated with, endorsed by, or maintained by OpenAI.

The server speaks remote MCP over Streamable HTTP at `/mcp`. It calls `https://api.ads.openai.com/v1` with `Authorization: Bearer $OPENAI_ADS_API_KEY`. Your MCP client authenticates to this server with a separate bearer token.

By default the process is read-only. Write tools are registered only when `MCP_READ_ONLY=false`. Campaigns, ad groups, and ads created through this server start **paused**.

## Features

- Ad account, campaign, ad group, and ad reads, including status and optional serving issues.
- Insights for a date range: impressions, clicks, spend, CTR, and CPC.
- Cursor pagination (`has_more`, `after`, `before`) with a page cap.
- Client-side limits of 600 requests per minute per endpoint and 1,200 per minute overall, plus bounded retries on HTTP 429.
- Optional writes: upload an image, create a paused campaign, ad group, and ad, then pause, activate, or edit them.
- Archive is not a separate tool. Setting `status` to `archived` on an update is irreversible and requires `confirm=true`.
- `GET /health` returns 200 with no credentials, for container health checks.
- `/mcp` requires `Authorization: Bearer $MCP_AUTH_TOKEN`. Secrets are not written to logs.

### Read tools

| Tool | Ads API |
| --- | --- |
| `get_ad_account` | `GET /ad_account` |
| `list_campaigns` | `GET /campaigns` |
| `list_ad_groups` | `GET /ad_groups?campaign_id=` |
| `list_ads` | `GET /ads?ad_group_id=` |
| `get_campaign_status` | `GET /campaigns/{campaign_id}` |
| `get_ad_group_status` | `GET /ad_groups/{ad_group_id}` |
| `get_ad_status` | `GET /ads/{ad_id}` |
| `get_performance_report` | `GET /ad_account/insights`, `GET /campaigns/{id}/insights`, `GET /ad_groups/{id}/insights`, or `GET /ads/{id}/insights` |

### Write tools

Registered only when `MCP_READ_ONLY=false`.

| Tool | Ads API |
| --- | --- |
| `upload_ad_image` | `POST /upload` with `image_url` |
| `create_campaign` | `POST /campaigns` with `status=paused` |
| `create_ad_group` | `POST /ad_groups` with `status=paused` |
| `create_ad` | `POST /ads` with `status=paused` |
| `pause_campaign`, `pause_ad_group`, `pause_ad` | `POST /{resource}/{id}/pause` |
| `activate_campaign`, `activate_ad_group`, `activate_ad` | `POST /{resource}/{id}/activate` |
| `update_campaign`, `update_ad_group`, `update_ad` | `POST /{resource}/{id}` |

A chat-card ad needs a `file_id` from `upload_ad_image` plus a `target_url`. Amounts are micros of the account currency (`1000000` micros = 1 currency unit). The minimum campaign budget value is `1000000`.

Typical create order: upload the image, create a paused campaign, create a paused ad group, create a paused ad, then call the activate tools when you want delivery.

## Requirements

- Python 3.11 or newer for a local install
- Docker, if you run the container
- An OpenAI Ads API key from Ads Manager
- A random string you choose as `MCP_AUTH_TOKEN`

The Python package pins the official MCP SDK `mcp==1.30.0`, which provides `FastMCP`. MCP Python SDK 2.x renamed that class, so this project stays on the 1.30 line.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
cp .env.example .env
```

Edit `.env` and set `OPENAI_ADS_API_KEY` and `MCP_AUTH_TOKEN`. Then:

```bash
set -a
source .env
set +a
openai-ads-mcp
```

The process listens on `0.0.0.0:8000`. Check it with:

```bash
curl -sS http://127.0.0.1:8000/health
```

Call MCP with the bearer token:

```bash
curl -sS http://127.0.0.1:8000/mcp \
  -H "Authorization: Bearer $MCP_AUTH_TOKEN" \
  -H "Accept: application/json, text/event-stream" \
  -H "Content-Type: application/json"
```

A request without that header receives `401`.

### MCP client configuration

```json
{
  "mcpServers": {
    "openai-ads": {
      "type": "streamable-http",
      "url": "https://<your-domain>/mcp",
      "headers": {
        "Authorization": "Bearer <MCP_AUTH_TOKEN>"
      }
    }
  }
}
```

For a local process, use `http://127.0.0.1:8000/mcp`. Put only `MCP_AUTH_TOKEN` in the client. The Ads API key stays in the server environment.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `OPENAI_ADS_API_KEY` | required | Ads API bearer token. Never logged. |
| `MCP_AUTH_TOKEN` | required | Bearer token required on `/mcp`. Never logged. |
| `MCP_READ_ONLY` | `true` | Write tools are registered only when this is `false`. Any other or missing value is read-only. |
| `HOST` | `0.0.0.0` | Bind address. |
| `PORT` | `8000` | Listen port. |
| `OPENAI_ADS_BASE_URL` | `https://api.ads.openai.com/v1` | Advertiser API origin. Override only for tests. |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, or `CRITICAL`. HTTP client header logs stay off. |
| `ADS_ENDPOINT_RATE_LIMIT` | `600` | Requests per minute for one endpoint, per process. |
| `ADS_GLOBAL_RATE_LIMIT` | `1200` | Requests per minute across endpoints, per process. |
| `ADS_RATE_WINDOW_SECONDS` | `60` | Window for those limits. |
| `ADS_MAX_RETRIES` | `5` | Extra attempts after HTTP 429. |
| `ADS_RETRY_BASE_SECONDS` | `1` | Exponential backoff base when `Retry-After` is absent. |
| `ADS_RETRY_MAX_SECONDS` | `30` | Cap for a single retry wait. |
| `ADS_REQUEST_TIMEOUT_SECONDS` | `30` | HTTP timeout. |
| `ADS_MAX_PAGES` | `25` | Maximum pages followed when `fetch_all` is true. |

Changing `MCP_READ_ONLY` applies on the next process start. Restart or redeploy after you change it.

The in-process limiter does not coordinate across replicas. The Ads API still enforces the account and IP quotas, and this server retries HTTP 429.

## Docker

Build and run from source:

```bash
docker build -t openai-ads-mcp:local .
docker run --rm -p 8000:8000 \
  -e OPENAI_ADS_API_KEY \
  -e MCP_AUTH_TOKEN \
  -e MCP_READ_ONLY=true \
  openai-ads-mcp:local
```

The image is multi-stage, based on `python:3.12-slim`, runs as a non-root user, and defines a `HEALTHCHECK` for `GET /health`. `MCP_READ_ONLY` defaults to `true` in the image.

### Docker Compose

`docker-compose.yml` builds this repository. It exposes port 8000 on the container network and does not publish a host port, which matches a proxy in front of the container (Coolify, Traefik, or another reverse proxy).

```bash
export OPENAI_ADS_API_KEY=...
export MCP_AUTH_TOKEN=...
docker compose up --build
```

The Compose file does not publish a host port. For a local check from your machine, use `docker run -p 8000:8000` above. Add a host port mapping only in a local override, and do not commit it if a reverse proxy is what reaches the container.

### Prebuilt image

GitHub Actions can publish this image to GHCR. The repository workflow does not run until you add this project to a GitHub repository and publish a release. The image name is lowercased:

```text
ghcr.io/<owner>/<repository>:0.1.0
ghcr.io/<owner>/<repository>:latest
```

Example:

```bash
docker pull ghcr.io/<owner>/<repository>:0.1.0
docker run --rm -p 8000:8000 \
  -e OPENAI_ADS_API_KEY \
  -e MCP_AUTH_TOKEN \
  ghcr.io/<owner>/<repository>:0.1.0
```

Building from this Dockerfile remains a supported way to run the server. The Compose file in the repo builds from source so a fresh checkout does not depend on GHCR.

The package is private to the repository until you change the GHCR package visibility. This repo does not publish to any other registry.

## Release process

1. Bump the version in `pyproject.toml`, `src/openai_ads_mcp/__init__.py` (`__version__`), and `CHANGELOG.md`.
2. Commit and push those changes.
3. Create a GitHub Release. Set the tag to `vX.Y.Z`, for example `v0.1.0`, and publish the release.
4. `.github/workflows/release.yml` runs when that release is published and when a `v*.*.*` tag is pushed. It also supports `workflow_dispatch` on a version tag.
5. The workflow checks out the code, sets up Buildx, logs in to `ghcr.io` as `${{ github.actor }}` with `GITHUB_TOKEN`, and pushes two tags: the semver version (`0.1.0`) and `latest`.

No other secret is required. A manual run has to use the tag ref, for example:

```bash
gh workflow run "Publish container image" --ref v0.1.0
```

Running the workflow from a branch, without a `vX.Y.Z` tag, stops before it pushes an image.

`.github/workflows/ci.yml` runs the unit tests on pull requests and on pushes.

## Reverse proxy and TLS

Terminate TLS at the proxy. Forward `https://<your-domain>/mcp` and `https://<your-domain>/health` to the container port `8000`. Preserve the `Authorization` header and the request path.

`/health` is the health check path and must not require the bearer token. `/mcp` must require it. The server is stateless Streamable HTTP, so the proxy does not need sticky sessions.

The default bind address is `0.0.0.0`, which accepts the `Host` header your proxy sends. Access to `/mcp` is still limited by the bearer token. If you set `HOST` to `127.0.0.1`, the server only accepts `localhost` Host headers.

Do not put the Ads API key in proxy access logs. This process does not log that key or `MCP_AUTH_TOKEN`.

## What you must change

Before anyone else can use a deployment, replace the placeholders:

1. **Ads API key.** Set `OPENAI_ADS_API_KEY` to the key from your Ads Manager settings. Treat it as a secret.
2. **MCP bearer token.** Set `MCP_AUTH_TOKEN` to a long random string you generate. This is not the Ads API key. Treat it as a secret.
3. **Domain.** At your proxy, choose the hostname clients will use and turn on HTTPS so the proxy can obtain a certificate. This repository does not contain a domain.
4. **Read-only or writes.** Leave `MCP_READ_ONLY=true` until you intend to create or change ads. Set it to `false` and restart the process to register write tools.
5. **Do not commit secrets.** Keep real values in the host environment or in an untracked `.env`. `.env.example` is only a template.

Coolify-specific clicks are in [docs/coolify.md](docs/coolify.md).

## Tests

```bash
python -m pip install -e ".[dev]"
python -m pytest
```

Tests mock HTTP. They cover pagination, 429 backoff, secret redaction, both `MCP_READ_ONLY` modes, paused creates, archive confirmation, and bearer auth on `/mcp`.

## License

MIT. See [LICENSE](LICENSE).
