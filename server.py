import os
import time
from collections.abc import Callable

import docker
import yaml
from flask import Flask, jsonify, request

from monitoring import logs_indicate_expired_license, normalize_docker_status


def create_app(config: dict, docker_client_factory: Callable[[], object]) -> Flask:
    app = Flask(__name__)
    checker_token = config["checker_token"]
    container_name = config["container_name"]

    @app.get("/api/v1/status")
    def status():
        if request.headers.get("Authorization") != f"Bearer {checker_token}":
            return jsonify(error="unauthorized"), 401

        try:
            container = docker_client_factory().containers.get(container_name)
            logs = container.logs(since=time.time() - 300)
            status = (
                "license_expired"
                if logs_indicate_expired_license(logs)
                else normalize_docker_status(container.status)
            )
        except (docker.errors.NotFound, docker.errors.DockerException):
            status = "not_found"

        return jsonify(container_name=container_name, status=status)

    return app


def main():
    config_path = os.environ.get("CONFIG_PATH", "./config.yaml")
    with open(config_path) as config_file:
        config = yaml.safe_load(config_file)

    create_app(config, docker.from_env).run(host="0.0.0.0", port=8080)


if __name__ == "__main__":
    main()
