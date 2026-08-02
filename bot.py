import os
import threading
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
            if not isinstance(payload, dict) or payload.get("status") not in CHECKER_STATUSES:
                return "server_unreachable"
            return payload["status"]
        except (requests.RequestException, ValueError):
            return "server_unreachable"


class StatusMonitor:
    def __init__(self, client: CheckerClient):
        self.client = client
        self._lock = threading.Lock()
        self.current_status = "server_unreachable"

    def refresh(self) -> str:
        status = self.client.fetch_status()
        if status not in REMOTE_STATUSES:
            status = "server_unreachable"
        with self._lock:
            self.current_status = status
        return status

    def get_status(self) -> str:
        with self._lock:
            return self.current_status


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
        if request.args.get("token", "") != page_token:
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
    monitor.refresh()
    create_app(config, monitor).run(host="0.0.0.0", port=8080)


if __name__ == "__main__":
    main()
