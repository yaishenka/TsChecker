LICENSE_EXPIRED_MESSAGE = "the default license has expired. please use the latest server version."
CHECKER_STATUSES = frozenset({"running", "stopped", "not_found", "restarting", "license_expired"})
REMOTE_STATUSES = CHECKER_STATUSES | {"server_unreachable"}


def normalize_docker_status(docker_status: str) -> str:
    return docker_status if docker_status in {"running", "restarting"} else "stopped"


def logs_indicate_expired_license(logs: bytes | str) -> bool:
    text = logs.decode(errors="replace") if isinstance(logs, bytes) else logs
    return LICENSE_EXPIRED_MESSAGE in text.lower()
