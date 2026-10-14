# Deploy on Coolify

This server is a small HTTP service. Coolify builds it from this Git repository and Traefik terminates TLS in front of port 8000.

The container listens on `0.0.0.0:8000`. `GET /health` returns 200 with no credentials. `POST /mcp` and `GET /mcp` require `Authorization: Bearer <MCP_AUTH_TOKEN>`.

## 1. Put the code in Git

Push this repository to the Git host Coolify can read. Do not commit `.env` or real tokens. The image is built from the Dockerfile in the repo. You do not need a prebuilt image.

## 2. Create the resource

1. In Coolify, add a new resource.
2. Choose your Git source and this repository. Pick the branch or tag you want to run.
3. Select the **Dockerfile** build pack, or the **Docker Compose** build pack if you want Coolify to use `docker-compose.yml`.
4. The Compose file builds from source, exposes port 8000, and does not publish a host port. Coolify's proxy reaches the container on the Docker network.

## 3. Domain and TLS

1. Set the public domain you control, for example the hostname you want clients to use.
2. Enable HTTPS so Traefik requests a certificate for that domain.
3. Point the service at container port **8000**.
4. Leave the path as `/` so both `/mcp` and `/health` are forwarded.
5. Do not strip the `Authorization` header.

## 4. Health check

Set the health check to:

| Setting | Value |
| --- | --- |
| Path | `/health` |
| Method | `GET` |
| Expected status | `200` |
| Port | `8000` |

`/health` must stay unauthenticated. A check that sends no bearer token is correct.

## 5. Environment variables

Set these on the resource. Mark `OPENAI_ADS_API_KEY` and `MCP_AUTH_TOKEN` as secrets so they are masked in the Coolify UI and not written into the image.

| Variable | Required | Notes |
| --- | --- | --- |
| `OPENAI_ADS_API_KEY` | Yes | Ads API key from Ads Manager. Secret. |
| `MCP_AUTH_TOKEN` | Yes | Long random string. Secret. Clients send it as a bearer token. |
| `MCP_READ_ONLY` | No | Defaults to `true`. Set to `false` only when write tools should be registered. |
| `PORT` | No | Defaults to `8000`. Keep the proxy and health check on the same port. |
| `HOST` | No | Defaults to `0.0.0.0`. |

Any value of `MCP_READ_ONLY` other than `false` (any case, surrounding spaces ignored) leaves the server read-only. An empty value is read-only.

Write tools are chosen when the process starts. After you change `MCP_READ_ONLY`, redeploy or restart the container. A running process does not pick up the new flag by itself.

## 6. Deploy

Start the deployment and wait until the health check is green. Then open `https://<your-domain>/health` in a browser. You should see `{"status":"ok"}` with no login prompt.

## 7. Connect an MCP client

Point the client at the Streamable HTTP endpoint and send the bearer token on every request:

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

Use the same token you stored as `MCP_AUTH_TOKEN`. Do not put the OpenAI Ads API key in the MCP client. The server sends that key to `https://api.ads.openai.com/v1`.

With `MCP_READ_ONLY=true`, the client sees only the read tools. Set `MCP_READ_ONLY=false`, redeploy, and reconnect to see create, pause, activate, and edit tools. New campaigns, ad groups, and ads are still created paused.
