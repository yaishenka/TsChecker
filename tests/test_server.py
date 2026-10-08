import time
from unittest.mock import Mock

import docker
import pytest
import requests

import server


def make_client(docker_client):
    app = server.create_app(
        {"checker_token": "checker-secret", "container_name": "ts"},
        docker_client_factory=lambda: docker_client,
    )
    return app.test_client()


# Bug caught: missing, null, empty, or non-string tokens can create an app that authenticates Bearer None.
@pytest.mark.parametrize(
    "config",
    [
        {"container_name": "ts"},
        {"checker_token": None, "container_name": "ts"},
        {"checker_token": "", "container_name": "ts"},
        {"checker_token": 1, "container_name": "ts"},
    ],
    ids=["missing", "null", "empty", "non-string"],
)
def test_create_app_rejects_invalid_checker_token(config):
    with pytest.raises(ValueError, match="checker_token must be a non-empty string"):
        server.create_app(config, docker_client_factory=Mock())


# Bug caught: an endpoint that exposes container status without bearer authentication.
def test_status_requires_bearer_token():
    response = make_client(Mock()).get("/api/v1/status")
    assert response.status_code == 401


# Bug caught: a running container masks an expired TS Server license in recent logs.
def test_license_log_overrides_running_status():
    container = Mock(status="running")
    container.logs.return_value = b"The default license has expired. Please use the latest server version."
    docker_client = Mock()
    docker_client.containers.get.return_value = container

    response = make_client(docker_client).get(
        "/api/v1/status", headers={"Authorization": "Bearer checker-secret"}
    )

    assert response.get_json() == {"container_name": "ts", "status": "license_expired"}


# Bug caught: passing a fixed `since=300` causes Docker to read logs from 1970.
def test_status_reads_logs_from_the_previous_five_minutes():
    container = Mock(status="running")
    container.logs.return_value = b""
    docker_client = Mock()
    docker_client.containers.get.return_value = container

    before_request = time.time()
    response = make_client(docker_client).get(
        "/api/v1/status", headers={"Authorization": "Bearer checker-secret"}
    )
    after_request = time.time()

    since = container.logs.call_args.kwargs["since"]
    assert before_request - 301 <= since <= after_request - 299
    assert response.get_json() == {"container_name": "ts", "status": "running"}


# Bug caught: a requests transport error while fetching a container becomes a Flask 500 response.
def test_container_get_request_error_returns_not_found():
    docker_client = Mock()
    docker_client.containers.get.side_effect = requests.RequestException("connection reset")

    response = make_client(docker_client).get(
        "/api/v1/status", headers={"Authorization": "Bearer checker-secret"}
    )

    assert response.get_json() == {"container_name": "ts", "status": "not_found"}


# Bug caught: a requests transport error while reading logs becomes a Flask 500 response.
def test_container_logs_request_error_returns_not_found():
    container = Mock(status="running")
    container.logs.side_effect = requests.RequestException("connection reset")
    docker_client = Mock()
    docker_client.containers.get.return_value = container

    response = make_client(docker_client).get(
        "/api/v1/status", headers={"Authorization": "Bearer checker-secret"}
    )

    assert response.get_json() == {"container_name": "ts", "status": "not_found"}


# Bug caught: Docker socket failures leak as server errors instead of checker not-found state.
def test_docker_error_returns_not_found():
    container = Mock(status="running")
    container.logs.side_effect = docker.errors.DockerException("socket unavailable")
    docker_client = Mock()
    docker_client.containers.get.return_value = container

    response = make_client(docker_client).get(
        "/api/v1/status", headers={"Authorization": "Bearer checker-secret"}
    )

    assert response.get_json()["status"] == "not_found"
