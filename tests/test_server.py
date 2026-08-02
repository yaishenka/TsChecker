from unittest.mock import Mock

import docker

import server


def make_client(docker_client):
    app = server.create_app(
        {"checker_token": "checker-secret", "container_name": "ts"},
        docker_client_factory=lambda: docker_client,
    )
    return app.test_client()


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
