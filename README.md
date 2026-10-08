# TsChecker

TsChecker monitors one Docker container across two hosts. A small checker runs
beside the TS container and exposes an authenticated JSON status endpoint. A
single remote-monitor container polls that endpoint, sends Telegram transition
notifications, answers `/ts_status`, and serves a token-protected status page.

## Requirements

- Docker and Docker Compose on both hosts
- Network access from the remote host to port 8080 on the TS host
- A Telegram bot token and the allowed Telegram chat IDs

Clone this repository on both hosts before following the matching section.

## 1. Deploy the checker on the TS host

The checker is the only service that reads the local Docker socket. Copy its
configuration and edit the token and exact TS container name:

```bash
cp config.checker.example.yaml config.checker.yaml
```

```yaml
checker_token: "replace-with-a-long-random-secret"
container_name: "target-container"
```

Start only the checker deployment:

```bash
docker compose -f docker-compose.checker.yml up --build -d
```

The checker publishes this contract on TS-host port 8080:

```text
GET /api/v1/status
Authorization: Bearer <checker-token>
```

A successful response is HTTP 200 JSON:

```json
{"container_name": "target-container", "status": "running"}
```

An absent or invalid bearer token returns HTTP 401. Restrict network access to
this port to the remote host where possible; the checker endpoint uses HTTP.

## 2. Deploy the monitor on the remote host

The remote deployment has no Docker socket access. Copy its configuration:

```bash
cp config.remote.example.yaml config.remote.yaml
```

Set `checker_url` to the TS host's reachable address, use the same
`checker_token`, and replace the page and Telegram secrets:

```yaml
page_token: "replace-with-another-long-random-secret"
checker_url: "http://<ts-host>:8080/api/v1/status"
checker_token: "replace-with-the-checker-secret"
request_timeout: 10
telegram:
  bot_token: "123456:ABC-your-bot-token"
  chat_ids: ["123456789"]
  poll_interval: 3600
  notify_on_start: false
  messages:
    running: "Container is UP"
    stopped: "Container is DOWN"
    not_found: "Container not found"
    restarting: "Container is restarting"
    license_expired: "TS license expired"
    server_unreachable: "TS checker is unreachable"
  command_messages:
    running: "Container is currently running"
```

`messages` controls transition notifications. `command_messages` can override
the reply for `/ts_status`; omitted command messages fall back to the matching
transition message and then to `Status: <status>`.

Start the single remote-monitor container:

```bash
docker compose -f docker-compose.remote.yml up --build -d
```

Open the protected page at:

```text
http://<remote-host>:1234/status?token=<page-token>
```

An invalid or missing page token returns HTTP 403. The Telegram bot accepts
`/ts_status` only from the configured `chat_ids`, and notifications are sent
only when the effective status changes (plus the initial state when
`notify_on_start` is true).

## Status meanings

| Status | Meaning |
| --- | --- |
| `running` | The TS container is running. |
| `stopped` | The container exists but is not running or restarting. |
| `restarting` | Docker reports that the container is restarting. |
| `not_found` | The container is absent, or the checker could not inspect Docker or its logs. |
| `license_expired` | Recent TS logs contain the default-license expiry message; this overrides Docker state. |
| `server_unreachable` | The remote monitor could not obtain a valid checker response. This remote-only status is never returned by the checker API. |

## Current HTTP-only boundary

Both the checker API and remote status page are intentionally HTTP-only. The
page token and checker bearer token are therefore not protected from network
observation. Use only within an appropriately trusted or restricted network.

DNS, Nginx, HTTPS/TLS, certificates, and domain routing are intentionally
deferred and are not part of this deployment.
