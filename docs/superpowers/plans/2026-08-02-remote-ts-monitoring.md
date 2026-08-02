# Remote TS Monitoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run a Docker-aware checker beside TS and a single remote container that polls it, serves the protected status page, and operates the Telegram bot.

**Architecture:** `server.py` becomes the TS-host checker, with an authenticated JSON API backed by the local Docker socket. `bot.py` becomes the remote monitor entry point: it contains an HTTP client, transition watcher, Telegram command loop, and Flask status page but never accesses Docker. Pure status rules live in `monitoring.py` so both roles have small, testable boundaries.

**Tech Stack:** Python 3.12, Flask, docker-py, requests, PyYAML, pytest, Docker Compose.

## Global Constraints

- Checker API is `GET /api/v1/status` and requires `Authorization: Bearer <checker-token>`.
- Checker statuses are `running`, `stopped`, `not_found`, `restarting`, and `license_expired` only.
- Checker scans exactly the previous 300 seconds of target-container logs; the configured default-license text is case-insensitive and overrides Docker state.
- Missing containers and all Docker inspection/logging errors return checker status `not_found`.
- Remote-only status `server_unreachable` covers HTTP failures, non-200 responses, invalid JSON, and unknown checker statuses.
- Remote compose exposes `1234:8080`; it has no Docker socket mount.
- DNS, Nginx, TLS, certificates, and domain routing are out of scope.

---

### Task 1: Extract Pure Status Rules

**Files:**
- Create: `monitoring.py`
- Create: `tests/test_monitoring.py`
- Create: `requirements-dev.txt`

**Interfaces:**
- Produces: `CHECKER_STATUSES: frozenset[str]`, `REMOTE_STATUSES: frozenset[str]`, `normalize_docker_status(docker_status: str) -> str`, `logs_indicate_expired_license(logs: bytes | str) -> bool`.
- Consumes: no project modules.

- [ ] **Step 1: Write the failing status-rule tests**

```python
from monitoring import logs_indicate_expired_license, normalize_docker_status


def test_normalize_docker_status_preserves_running_and_restarting():
    assert normalize_docker_status("running") == "running"
    assert normalize_docker_status("restarting") == "restarting"


def test_normalize_docker_status_maps_other_states_to_stopped():
    assert normalize_docker_status("exited") == "stopped"
    assert normalize_docker_status("paused") == "stopped"


def test_license_message_is_case_insensitive_for_bytes_and_text():
    text = "THE DEFAULT LICENSE HAS EXPIRED. PLEASE USE THE LATEST SERVER VERSION."
    assert logs_indicate_expired_license(text)
    assert logs_indicate_expired_license(text.encode())
```

- [ ] **Step 2: Run the status-rule test to verify it fails**

Run: `python -m pytest tests/test_monitoring.py -q`

Expected: FAIL because `monitoring` does not exist.

- [ ] **Step 3: Implement the minimal pure status module**

```python
LICENSE_EXPIRED_MESSAGE = "the default license has expired. please use the latest server version."
CHECKER_STATUSES = frozenset({"running", "stopped", "not_found", "restarting", "license_expired"})
REMOTE_STATUSES = CHECKER_STATUSES | {"server_unreachable"}


def normalize_docker_status(docker_status: str) -> str:
    return docker_status if docker_status in {"running", "restarting"} else "stopped"


def logs_indicate_expired_license(logs: bytes | str) -> bool:
    text = logs.decode(errors="replace") if isinstance(logs, bytes) else logs
    return LICENSE_EXPIRED_MESSAGE in text.lower()
```

- [ ] **Step 4: Run the focused test to verify it passes**

Run: `python -m pytest tests/test_monitoring.py -q`

Expected: PASS with 3 tests.

- [ ] **Step 5: Add the test dependency and commit**

Create `requirements-dev.txt` containing `pytest`, then run:

```bash
git add monitoring.py tests/test_monitoring.py requirements-dev.txt
git commit -m "feat: add shared TS status rules"
```

### Task 2: Implement the TS-Host Checker API

**Files:**
- Modify: `server.py`
- Create: `tests/test_server.py`
- Create: `config.checker.example.yaml`
- Create: `docker-compose.checker.yml`
- Modify: `Dockerfile`

**Interfaces:**
- Consumes: `monitoring.normalize_docker_status`, `monitoring.logs_indicate_expired_license`.
- Produces: `create_app(config: dict, docker_client_factory: Callable[[], object]) -> Flask` and `GET /api/v1/status`.

- [ ] **Step 1: Write failing checker API tests**

```python
from unittest.mock import Mock

import docker

from server import create_app


def make_client(docker_client):
    app = create_app(
        {"checker_token": "checker-secret", "container_name": "ts"},
        docker_client_factory=lambda: docker_client,
    )
    return app.test_client()


def test_status_requires_bearer_token():
    response = make_client(Mock()).get("/api/v1/status")
    assert response.status_code == 401


def test_license_log_overrides_running_status():
    container = Mock(status="running")
    container.logs.return_value = b"The default license has expired. Please use the latest server version."
    docker_client = Mock()
    docker_client.containers.get.return_value = container
    response = make_client(docker_client).get("/api/v1/status", headers={"Authorization": "Bearer checker-secret"})
    assert response.get_json() == {"container_name": "ts", "status": "license_expired"}


def test_docker_error_returns_not_found():
    container = Mock(status="running")
    container.logs.side_effect = docker.errors.DockerException("socket unavailable")
    docker_client = Mock()
    docker_client.containers.get.return_value = container
    response = make_client(docker_client).get("/api/v1/status", headers={"Authorization": "Bearer checker-secret"})
    assert response.get_json()["status"] == "not_found"
```

- [ ] **Step 2: Run the checker tests to verify they fail**

Run: `python -m pytest tests/test_server.py -q`

Expected: FAIL because the current server exposes only `/status` and returns HTML.

- [ ] **Step 3: Replace the old local page role with the JSON checker role**

Implement a config-loaded `create_app`. Compare the whole Authorization header with `Bearer <checker_token>`, retrieve the configured container, call `container.logs(since=300)`, then return `jsonify(container_name=..., status=...)`. Catch `docker.errors.NotFound` and every `docker.errors.DockerException` around container inspection and log reads, returning `not_found`. Run `app.run(host="0.0.0.0", port=8080)` only inside `main()`.

- [ ] **Step 4: Add checker deployment configuration**

Create this shape in `config.checker.example.yaml`:

```yaml
checker_token: "change-me"
container_name: "target-container"
```

Create `docker-compose.checker.yml` with one `checker` service, read-only `./config.checker.yaml:/app/config.yaml`, read-only Docker socket, `CONFIG_PATH=/app/config.yaml`, command `python -u server.py`, restart policy `unless-stopped`, and an explicit API host-port mapping.

- [ ] **Step 5: Run checker tests and commit**

Run: `python -m pytest tests/test_server.py tests/test_monitoring.py -q`

Expected: PASS.

```bash
git add server.py config.checker.example.yaml docker-compose.checker.yml Dockerfile tests/test_server.py
git commit -m "feat: expose TS checker status API"
```

### Task 3: Build the Remote Status Client and Page

**Files:**
- Modify: `bot.py`
- Create: `tests/test_bot.py`
- Create: `config.remote.example.yaml`
- Create: `docker-compose.remote.yml`

**Interfaces:**
- Consumes: `monitoring.CHECKER_STATUSES`, `monitoring.REMOTE_STATUSES`.
- Produces: `CheckerClient(url: str, token: str, timeout: int, http_get: Callable = requests.get)`, `CheckerClient.fetch_status() -> str`, `StatusMonitor.refresh() -> str`, `create_app(config: dict, monitor: StatusMonitor) -> Flask`.

- [ ] **Step 1: Write failing remote client and page tests**

```python
import requests

from bot import CheckerClient, StatusMonitor, create_app


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self.payload = payload

    def json(self):
        return self.payload


def test_request_exception_becomes_server_unreachable():
    def failing_get(*args, **kwargs):
        raise requests.RequestException("timeout")

    client = CheckerClient("http://checker/api/v1/status", "secret", 10, failing_get)
    assert client.fetch_status() == "server_unreachable"


def test_unknown_checker_status_becomes_server_unreachable():
    client = CheckerClient(
        "http://checker/api/v1/status", "secret", 10,
        lambda *args, **kwargs: FakeResponse(200, {"status": "broken"}),
    )
    assert client.fetch_status() == "server_unreachable"


def test_page_renders_remote_status_and_rejects_bad_token():
    monitor = StatusMonitor(CheckerClient("http://checker", "secret", 10))
    monitor.current_status = "server_unreachable"
    page_client = create_app({"page_token": "page-secret", "container_name": "ts"}, monitor).test_client()
    assert page_client.get("/status?token=wrong").status_code == 403
    response = page_client.get("/status?token=page-secret")
    assert response.status_code == 200
    assert b"server_unreachable" in response.data
```

- [ ] **Step 2: Run the remote test to verify it fails**

Run: `python -m pytest tests/test_bot.py -q`

Expected: FAIL because the existing bot reads Docker locally and has no Flask application factory.

- [ ] **Step 3: Implement the remote polling client and page**

`CheckerClient` must issue `requests.get(checker_url, headers={"Authorization": f"Bearer {checker_token}"}, timeout=timeout)`, require HTTP 200 and a JSON object whose `status` belongs to `CHECKER_STATUSES`. Otherwise it returns `server_unreachable`. `StatusMonitor` stores its current effective status behind a lock, provides `refresh()`, and supplies it to a Flask `/status` route protected by the page token. Reuse the existing page layout with colors for all checker and remote statuses.

- [ ] **Step 4: Add remote configuration and compose manifest**

Create `config.remote.example.yaml` with this complete structure:

```yaml
page_token: "change-me"
checker_url: "http://ts-host:8080/api/v1/status"
checker_token: "change-me"
request_timeout: 10
telegram:
  bot_token: "123456:ABC-your-bot-token"
  chat_ids: ["123456789"]
  poll_interval: 3600
  notify_on_start: false
  messages: {}
  command_messages: {}
```

Create `docker-compose.remote.yml` with one service, no Docker socket mount, read-only `./config.remote.yaml:/app/config.yaml`, `CONFIG_PATH=/app/config.yaml`, `1234:8080`, command `python -u bot.py`, and `restart: unless-stopped`.

- [ ] **Step 5: Run remote tests and commit**

Run: `python -m pytest tests/test_bot.py tests/test_monitoring.py -q`

Expected: PASS.

```bash
git add bot.py config.remote.example.yaml docker-compose.remote.yml tests/test_bot.py
git commit -m "feat: add remote TS monitor page"
```

### Task 4: Integrate Telegram Monitoring and Document Two-Host Deployment

**Files:**
- Modify: `bot.py`
- Modify: `tests/test_bot.py`
- Modify: `README.md`
- Delete: `docker-compose.yml`
- Delete: `config.example.yaml`

**Interfaces:**
- Consumes: `StatusMonitor.refresh() -> str`, `REMOTE_STATUSES` and remote configuration from Task 3.
- Produces: `Watcher.check_once() -> str`, `TelegramBot.handle_command(text: str, chat_id: str) -> None`, `monitor_loop() -> None`, `command_listener() -> None`, and two documented Docker Compose invocation paths.

- [ ] **Step 1: Write failing watcher behaviour tests**

```python
from unittest.mock import Mock, call

from bot import TelegramBot, Watcher


def test_watcher_notifies_only_when_effective_status_changes():
    monitor = Mock()
    monitor.refresh.side_effect = ["running", "running", "license_expired"]
    send_message = Mock()
    watcher = Watcher(
        monitor, ["123456789"],
        {"running": "Container is UP", "license_expired": "License expired"},
        send_message, notify_on_start=True,
    )
    watcher.check_once()
    watcher.check_once()
    watcher.check_once()
    assert send_message.call_args_list == [call("Container is UP", "123456789"), call("License expired", "123456789")]


def test_ts_status_refreshes_before_reply_when_no_cached_status():
    monitor = Mock(current_status=None)
    monitor.refresh.return_value = "running"
    send_message = Mock()
    telegram = TelegramBot(
        monitor, {"123456789"}, {"running": "Container is currently running"}, send_message,
    )
    telegram.handle_command("/ts_status", "123456789")
    assert send_message.call_args == call("Container is currently running", "123456789")
```

- [ ] **Step 2: Run the watcher test to verify it fails**

Run: `python -m pytest tests/test_bot.py -q`

Expected: FAIL because Task 3 does not yet send transition notifications or expose a testable command handler.

- [ ] **Step 3: Connect watcher and Telegram command loop to the remote monitor**

Make the watcher call `Watcher.check_once()` at `telegram.poll_interval` and broadcast only on a changed effective status, observing `notify_on_start`. Implement `TelegramBot.handle_command()` so `/ts_status` uses `StatusMonitor.refresh()` when the cache is empty and otherwise uses the cached status. Keep long-polling `getUpdates`, allowed-chat filtering, configurable message templates, and recoverable Telegram request errors.

- [ ] **Step 4: Rewrite deployment documentation**

Replace the current single-host README with separate numbered sections for TS-host checker and remote monitor. Include config-copy commands, start commands using the matching compose file, the endpoint contract, status meanings, remote page URL `http://<remote-host>:1234/status?token=...`, and the HTTP-only warning. State explicitly that DNS, Nginx, and HTTPS are intentionally deferred.

- [ ] **Step 5: Run complete verification and commit**

Run:

```bash
python -m pytest -q
docker compose -f docker-compose.checker.yml config
docker compose -f docker-compose.remote.yml config
git diff --check
```

Expected: all tests pass, both compose files render successfully, and the diff has no whitespace errors.

```bash
git add README.md bot.py tests/test_bot.py docker-compose.yml config.example.yaml
git commit -m "docs: describe two-host TS monitoring"
```
