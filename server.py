import os
import yaml
import docker
from flask import Flask, request

app = Flask(__name__)

CONFIG_PATH = os.environ.get("CONFIG_PATH", "./config.yaml")

with open(CONFIG_PATH) as f:
    config = yaml.safe_load(f)

TOKEN = config["token"]
CONTAINER_NAME = config["container_name"]

_docker_client = None


def get_docker_client():
    global _docker_client
    if _docker_client is None:
        _docker_client = docker.from_env()
    return _docker_client


STATUS_COLORS = {
    "running": "#2ecc71",
    "exited": "#e74c3c",
    "paused": "#f39c12",
    "restarting": "#3498db",
    "dead": "#e74c3c",
    "created": "#95a5a6",
    "not_found": "#e74c3c",
}


def render_page(container_name, status, error=None):
    color = STATUS_COLORS.get(status, "#95a5a6")
    detail = f'<p style="color:#888;font-size:0.9em">{error}</p>' if error else ""
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
    {detail}
  </div>
</body>
</html>"""


@app.route("/status")
def status():
    token = request.args.get("token", "")
    if token != TOKEN:
        return (
            "<h2>403 Forbidden</h2><p>Invalid or missing token.</p>",
            403,
            {"Content-Type": "text/html"},
        )

    try:
        client = get_docker_client()
        container = client.containers.get(CONTAINER_NAME)
        container_status = container.status
    except docker.errors.NotFound:
        container_status = "not_found"
    except docker.errors.DockerException as e:
        return render_page(CONTAINER_NAME, "error", str(e)), 503

    return render_page(CONTAINER_NAME, container_status)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
