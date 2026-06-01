# TsChecker

A minimal HTTP server that exposes a browser-friendly status page for a Docker container running on the same host. Includes a Telegram bot that sends notifications when the container status changes. Access to the status page is protected by a token passed in the URL.

## Requirements

- Docker
- Docker Compose

## Setup

**1. Clone the repo and enter the directory:**

```bash
git clone <repo-url>
cd TsChecker
```

**2. Copy the example config and edit it:**

```bash
cp config.example.yaml config.yaml
```

```yaml
token: "your-secret-token"      # used to authenticate the status page URL
container_name: "my-container"  # name of the container to monitor
telegram:
  bot_token: "123456:ABC-your-bot-token"  # from @BotFather
  chat_id: "123456789"                    # target chat or user ID
  poll_interval: 3600                     # check interval in seconds (default: 1 hour)
  messages:
    running: "Container is UP"
    stopped: "Container is DOWN"
    not_found: "Container not found"
```

**3. Build and start:**

```bash
docker compose up --build -d
```

## Usage

Open in a browser:

```
http://localhost:1234/status?token=your-secret-token
```

The page displays the container name and its current status (e.g. `running`, `exited`, `not_found`).

An invalid or missing token returns a **403** page.

## Configuration

| Field                        | Description                                      |
|------------------------------|--------------------------------------------------|
| `token`                      | Secret token required in the status page URL     |
| `container_name`             | Name of the Docker container to monitor          |
| `telegram.bot_token`         | Telegram bot token from @BotFather               |
| `telegram.chat_id`           | Chat or user ID to send notifications to         |
| `telegram.poll_interval`     | How often to check status, in seconds            |
| `telegram.messages.<status>` | Custom text for each status (`running`, `stopped`, `not_found`, etc.) |

The config file is mounted read-only into the containers at `/app/config.yaml`. To apply changes, restart the services:

```bash
docker compose restart
```

## Telegram Bot

The `tsbot` service polls the container status every `poll_interval` seconds. When the status changes, it sends the corresponding message from `config.yaml` to the configured chat.

To get a bot token: message [@BotFather](https://t.me/BotFather) on Telegram and use `/newbot`.
To get your chat ID: message [@userinfobot](https://t.me/userinfobot).

## Sharing the link

Share the full URL including the token with anyone who needs to check the status:

```
http://<your-host>:1234/status?token=your-secret-token
```
