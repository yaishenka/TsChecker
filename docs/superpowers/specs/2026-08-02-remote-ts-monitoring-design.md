# Remote TS Monitoring Design

## Goal

Split TS monitoring between two hosts: a checker next to the TS Docker
container and a single remote service that polls the checker, serves the
status page, and communicates with Telegram.

## Scope

This design deliberately excludes DNS, Nginx, TLS, certificate management,
and public-domain routing. The remote service is initially exposed directly
on its existing HTTP port. A separate future change can add those concerns
without changing the status protocol.

## Architecture

The repository will provide two independent Docker Compose deployments that
share one Python image:

- **TS-host checker.** It is the only deployment with read-only access to
  `/var/run/docker.sock`. It exposes an authenticated JSON API for one target
  container.
- **Remote monitor.** It has no Docker socket. One container runs the polling
  watcher, Telegram command listener, and protected status page. It requests
  the checker API over HTTP.

Each deployment has its own example YAML file. Operators copy the matching
example to a local, ignored configuration file before starting the associated
compose file.

## Checker API

The TS-host checker exposes:

```text
GET /api/v1/status
Authorization: Bearer <checker-token>
```

A successful response has HTTP 200 and JSON of this form:

```json
{
  "container_name": "target-container",
  "status": "running"
}
```

The value of `status` is exactly one of:

`running`, `stopped`, `not_found`, `restarting`, `license_expired`.

Docker states map as follows:

| Docker result | API status |
| --- | --- |
| `running` | `running` |
| `restarting` | `restarting` |
| `created`, `exited`, `paused`, `dead`, or another non-running state | `stopped` |
| missing container or Docker API error | `not_found` |

After locating the container, checker reads only its last 300 seconds of
logs. If those logs contain `The default license has expired. Please use the
latest server version.` (case-insensitively), it returns `license_expired`,
which takes priority over the Docker state. Failure to inspect the container
or read its logs returns `not_found`.

An absent or invalid bearer token returns HTTP 401 and no container status.

## Remote Monitor

The remote configuration supplies `checker_url`, `checker_token`, request
timeout, polling interval, Telegram credentials, allowed chat IDs, page
token, and per-status notification and command messages.

The remote monitor requests the checker endpoint with the bearer token. A
network failure, timeout, non-200 response, malformed JSON, or unknown
checker status becomes the local status `server_unreachable`. This status is
also used by Telegram and the page. It is not returned by the checker API.

Watcher behaviour:

- poll at the configured interval;
- notify configured chats only when the effective status changes;
- preserve the existing optional `notify_on_start` behaviour;
- reply to `/ts_status` in an allowed chat with the most recently fetched
  status, fetching it first if no status has been observed yet.

The status page remains token-protected and keeps the existing shape:

```text
GET /status?token=<page-token>
```

It renders the latest effective remote status. Invalid or missing page tokens
return HTTP 403. The remote deployment maps host port 1234 to container port
8080 for the initial HTTP-only setup.

## Deployment Files

The implementation will replace the current single-host compose arrangement
with two documented entry points:

- `docker-compose.checker.yml`: TS-host checker only; mounts the Docker socket
  read-only and publishes the checker API port.
- `docker-compose.remote.yml`: remote monitor only; does not mount Docker and
  publishes `1234:8080` for the status page.

The shared image includes all runtime modules needed by both roles. The
README will give separate setup and start commands for each host and document
the HTTP-only limitation without adding web-proxy instructions.

## Testing

Automated tests will cover:

- Docker-to-public status normalization;
- `license_expired` detection over a five-minute log window and its priority;
- `not_found` on absent containers and Docker failures;
- checker bearer-token rejection and successful JSON output;
- remote conversion of request failures and invalid checker payloads to
  `server_unreachable`;
- watcher notifications only on effective status transitions;
- page-token protection and rendering of the remote status.

## Non-goals

- Controlling, restarting, or otherwise mutating the TS container.
- Telegram webhooks; the bot remains pull-based through `getUpdates`.
- Nginx, DNS records, TLS, certificate issuance, and domain routing.
- Monitoring more than one TS container per deployment.
