import os
import threading
import time
from collections.abc import Callable

import requests
import yaml
from flask import Flask, request

from monitoring import CHECKER_STATUSES, REMOTE_STATUSES


STATUS_COLORS = {
    "running": "#2ecc71",
    "stopped": "#e74c3c",
    "not_found": "#e74c3c",
    "restarting": "#3498db",
    "license_expired": "#f39c12",
    "server_unreachable": "#95a5a6",
}


class CheckerClient:
    def __init__(
        self,
        url: str,
        token: str,
        timeout: int,
        http_get: Callable = requests.get,
    ):
        self.url = url
        self.token = token
        self.timeout = timeout
        self.http_get = http_get

    def fetch_status(self) -> str:
        try:
            response = self.http_get(
                self.url,
                headers={"Authorization": f"Bearer {self.token}"},
                timeout=self.timeout,
            )
            if response.status_code != 200:
                return "server_unreachable"

            payload = response.json()
            if not isinstance(payload, dict):
                return "server_unreachable"
            status = payload.get("status")
            if not isinstance(status, str) or status not in CHECKER_STATUSES:
                return "server_unreachable"
            return status
        except (requests.RequestException, ValueError):
            return "server_unreachable"


class StatusMonitor:
    def __init__(self, client: CheckerClient):
        self.client = client
        self._lock = threading.Lock()
        self._refresh_lock = threading.Lock()
        self.current_status = None

    def refresh(self) -> str:
        with self._refresh_lock:
            status = self.client.fetch_status()
            if status not in REMOTE_STATUSES:
                status = "server_unreachable"
            with self._lock:
                self.current_status = status
        return status

    def get_status(self) -> str | None:
        with self._lock:
            return self.current_status


class Watcher:
    def __init__(
        self,
        monitor: StatusMonitor,
        chat_ids: list[str],
        messages: dict[str, str],
        send_message: Callable[[str, str], None],
        notify_on_start: bool = False,
    ):
        self.monitor = monitor
        self.chat_ids = chat_ids
        self.messages = messages
        self.send_message = send_message
        self.notify_on_start = notify_on_start
        self.previous_status = None

    def check_once(self) -> str:
        status = self.monitor.refresh()
        changed = status != self.previous_status
        should_notify = changed and (
            self.previous_status is not None or self.notify_on_start
        )
        if should_notify:
            message = self.messages.get(status, f"Status: {status}")
            for chat_id in self.chat_ids:
                self.send_message(message, chat_id)
        self.previous_status = status
        return status


class TelegramBot:
    def __init__(
        self,
        monitor: StatusMonitor,
        chat_ids: set[str],
        command_messages: dict[str, str],
        send_message: Callable[[str, str], None],
        api_base: str = "",
        http_get: Callable = requests.get,
    ):
        self.monitor = monitor
        self.chat_ids = chat_ids
        self.command_messages = command_messages
        self.send_message = send_message
        self.api_base = api_base
        self.http_get = http_get

    def handle_command(self, text: str, chat_id: str) -> None:
        command = text.split(maxsplit=1)[0] if text else ""
        is_status_command = command == "/ts_status" or (
            command.startswith("/ts_status@") and len(command) > len("/ts_status@")
        )
        if chat_id not in self.chat_ids or not is_status_command:
            return
        status = self.monitor.get_status()
        if status is None:
            status = self.monitor.refresh()
        message = self.command_messages.get(status, f"Status: {status}")
        self.send_message(message, chat_id)

    def poll_once(self, offset: int | None) -> int | None:
        params = {"timeout": 30, "allowed_updates": ["message"]}
        if offset is not None:
            params["offset"] = offset
        response = self.http_get(
            f"{self.api_base}/getUpdates", params=params, timeout=35
        )
        response.raise_for_status()
        payload = response.json()
        if (
            not isinstance(payload, dict)
            or payload.get("ok") is not True
            or not isinstance(payload.get("result"), list)
        ):
            raise ValueError("invalid Telegram getUpdates payload")
        updates = payload["result"]
        for update in updates:
            if not isinstance(update, dict) or not isinstance(
                update.get("update_id"), int
            ):
                raise ValueError("invalid Telegram getUpdates payload")
            offset = update["update_id"] + 1
            message = update.get("message", {})
            if not isinstance(message, dict):
                raise ValueError("invalid Telegram getUpdates payload")
            chat = message.get("chat", {})
            if not isinstance(chat, dict):
                raise ValueError("invalid Telegram getUpdates payload")
            text = message.get("text", "")
            if not isinstance(text, str):
                text = ""
            self.handle_command(text, str(chat.get("id", "")))
        return offset


def make_send_message(
    bot_token: str, http_post: Callable = requests.post
) -> Callable[[str, str], None]:
    api_base = f"https://api.telegram.org/bot{bot_token}"

    def send_message(text: str, chat_id: str) -> None:
        try:
            response = http_post(
                f"{api_base}/sendMessage",
                json={"chat_id": chat_id, "text": text},
                timeout=10,
            )
            response.raise_for_status()
        except requests.RequestException as error:
            print(f"[telegram] failed to send to {chat_id}: {error}")

    return send_message


def monitor_loop(
    watcher: Watcher,
    poll_interval: int,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    while True:
        watcher.check_once()
        sleep(poll_interval)


def command_listener(
    telegram: TelegramBot,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    offset = None
    while True:
        try:
            offset = telegram.poll_once(offset)
        except requests.RequestException as error:
            print(f"[commands] request error: {error}")
            sleep(5)
        except (KeyError, TypeError, ValueError) as error:
            print(f"[commands] invalid Telegram response: {error}")
            sleep(5)


def render_page(container_name: str, status: str) -> str:
    if status not in REMOTE_STATUSES:
        status = "server_unreachable"
    color = STATUS_COLORS[status]
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Container Status</title>
  <style>
    body {{ font-family: sans-serif; display: flex; justify-content: center;
           align-items: center; height: 100vh; margin: 0; background: #f5f5f5; }}
    .card {{ background: white; border-radius: 8px; padding: 2rem 3rem;
             box-shadow: 0 2px 8px rgba(0,0,0,.12); text-align: center; }}
    .badge {{ display: inline-block; padding: .4em 1em; border-radius: 4px;
              background: {color}; color: white; font-size: 1.2em; font-weight: bold; }}
  </style>
</head>
<body>
  <div class="card">
    <h2 style="margin-top:0">{container_name}</h2>
    <span class="badge">{status}</span>
  </div>
</body>
</html>"""


def create_app(config: dict, monitor: StatusMonitor) -> Flask:
    app = Flask(__name__)
    page_token = config["page_token"]
    container_name = config.get("container_name", "TS Server")

    @app.get("/status")
    def status():
        if not page_token or request.args.get("token") != page_token:
            return (
                "<h2>403 Forbidden</h2><p>Invalid or missing token.</p>",
                403,
                {"Content-Type": "text/html"},
            )
        return render_page(container_name, monitor.get_status())

    return app


def main():
    config_path = os.environ.get("CONFIG_PATH", "./config.yaml")
    with open(config_path) as config_file:
        config = yaml.safe_load(config_file)

    client = CheckerClient(
        config["checker_url"],
        config["checker_token"],
        int(config.get("request_timeout", 10)),
    )
    monitor = StatusMonitor(client)
    telegram_config = config["telegram"]
    bot_token = telegram_config["bot_token"]
    chat_ids = {str(chat_id) for chat_id in telegram_config["chat_ids"]}
    poll_interval = int(telegram_config.get("poll_interval", 3600))
    messages = telegram_config.get("messages", {})
    command_overrides = telegram_config.get("command_messages", {})
    command_messages = {
        status: command_overrides.get(
            status, messages.get(status, f"Status: {status}")
        )
        for status in REMOTE_STATUSES
    }
    send_message = make_send_message(bot_token)
    watcher = Watcher(
        monitor,
        sorted(chat_ids),
        messages,
        send_message,
        notify_on_start=bool(telegram_config.get("notify_on_start", False)),
    )
    telegram = TelegramBot(
        monitor,
        chat_ids,
        command_messages,
        send_message,
        api_base=f"https://api.telegram.org/bot{bot_token}",
    )
    threading.Thread(
        target=monitor_loop, args=(watcher, poll_interval), daemon=True
    ).start()
    threading.Thread(target=command_listener, args=(telegram,), daemon=True).start()
    create_app(config, monitor).run(host="0.0.0.0", port=8080)


if __name__ == "__main__":
    main()
