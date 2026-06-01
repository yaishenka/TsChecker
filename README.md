# TsChecker

A minimal HTTP server that exposes a browser-friendly status page for a Docker container running on the same host. Access is protected by a token passed in the URL.

## Requirements

- Docker
- Docker Compose

## Setup

**1. Clone the repo and enter the directory:**

```bash
git clone <repo-url>
cd TsChecker
```

**2. Edit `config.yaml`:**

```yaml
token: "your-secret-token"      # used to authenticate requests
container_name: "my-container"  # name of the container to monitor
```

**3. Build and start:**

```bash
docker compose up --build -d
```

## Usage

Open in a browser:

```
http://localhost:8080/status?token=your-secret-token
```

The page displays the container name and its current status (e.g. `running`, `exited`, `not_found`).

An invalid or missing token returns a **403** page.

## Configuration

| Field            | Description                              |
|------------------|------------------------------------------|
| `token`          | Secret token required in the URL         |
| `container_name` | Name of the Docker container to check    |

The config file is mounted read-only into the container at `/app/config.yaml`. To apply changes, restart the service:

```bash
docker compose restart
```

## Sharing the link

Share the full URL including the token with anyone who needs to check the status:

```
http://<your-host>:8080/status?token=your-secret-token
```
