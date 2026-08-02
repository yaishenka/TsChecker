import requests

from bot import CheckerClient, StatusMonitor, create_app


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self.payload = payload

    def json(self):
        return self.payload


class MalformedJsonResponse:
    status_code = 200

    def json(self):
        raise ValueError("malformed JSON")


# Bug caught: the checker bearer token or configured timeout is omitted or changed in transit.
def test_checker_request_uses_bearer_token_and_configured_timeout():
    observed = {}

    def recording_get(url, **kwargs):
        observed["url"] = url
        observed.update(kwargs)
        return FakeResponse(200, {"status": "running"})

    client = CheckerClient(
        "http://checker/api/v1/status", "secret", 17, recording_get
    )

    assert client.fetch_status() == "running"
    assert observed == {
        "url": "http://checker/api/v1/status",
        "headers": {"Authorization": "Bearer secret"},
        "timeout": 17,
    }


# Bug caught: a checker request failure escapes instead of becoming the remote fallback state.
def test_request_exception_becomes_server_unreachable():
    def failing_get(*args, **kwargs):
        raise requests.RequestException("timeout")

    client = CheckerClient("http://checker/api/v1/status", "secret", 10, failing_get)
    assert client.fetch_status() == "server_unreachable"


# Bug caught: an unrecognized checker state leaks into the remote monitor and status page.
def test_unknown_checker_status_becomes_server_unreachable():
    client = CheckerClient(
        "http://checker/api/v1/status",
        "secret",
        10,
        lambda *args, **kwargs: FakeResponse(200, {"status": "broken"}),
    )
    assert client.fetch_status() == "server_unreachable"


# Bug caught: a checker response without status is treated as a usable remote state.
def test_missing_checker_status_becomes_server_unreachable():
    client = CheckerClient(
        "http://checker/api/v1/status",
        "secret",
        10,
        lambda *args, **kwargs: FakeResponse(200, {}),
    )
    assert client.fetch_status() == "server_unreachable"


# Bug caught: an unhashable checker status raises TypeError instead of using the fallback state.
def test_list_checker_status_becomes_server_unreachable():
    client = CheckerClient(
        "http://checker/api/v1/status",
        "secret",
        10,
        lambda *args, **kwargs: FakeResponse(200, {"status": []}),
    )
    assert client.fetch_status() == "server_unreachable"


# Bug caught: a non-success checker response is mistaken for a valid status response.
def test_non_200_checker_response_becomes_server_unreachable():
    client = CheckerClient(
        "http://checker/api/v1/status",
        "secret",
        10,
        lambda *args, **kwargs: FakeResponse(503, {"status": "running"}),
    )
    assert client.fetch_status() == "server_unreachable"


# Bug caught: malformed checker JSON escapes instead of becoming the remote fallback state.
def test_malformed_checker_json_becomes_server_unreachable():
    client = CheckerClient(
        "http://checker/api/v1/status",
        "secret",
        10,
        lambda *args, **kwargs: MalformedJsonResponse(),
    )
    assert client.fetch_status() == "server_unreachable"


# Bug caught: the page exposes status without its token or ignores the monitor's cached state.
def test_page_renders_remote_status_and_rejects_bad_token():
    monitor = StatusMonitor(CheckerClient("http://checker", "secret", 10))
    monitor.current_status = "server_unreachable"
    page_client = create_app(
        {"page_token": "page-secret", "container_name": "ts"}, monitor
    ).test_client()
    assert page_client.get("/status?token=wrong").status_code == 403
    response = page_client.get("/status?token=page-secret")
    assert response.status_code == 200
    assert b"server_unreachable" in response.data


# Bug caught: the documented remote config crashes the page because it has no container_name.
def test_page_accepts_complete_remote_config_without_container_name():
    monitor = StatusMonitor(CheckerClient("http://checker", "secret", 10))
    page_client = create_app({"page_token": "page-secret"}, monitor).test_client()

    response = page_client.get("/status?token=page-secret")

    assert response.status_code == 200
    assert b"TS Server" in response.data


# Bug caught: an empty configured token authorizes a request with no page token at all.
def test_missing_page_token_is_forbidden_when_configured_token_is_empty():
    monitor = StatusMonitor(CheckerClient("http://checker", "secret", 10))
    page_client = create_app({"page_token": ""}, monitor).test_client()

    assert page_client.get("/status").status_code == 403
    assert page_client.get("/status?token=").status_code == 403
