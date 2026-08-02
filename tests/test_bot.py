from unittest.mock import Mock, call

import requests
import pytest

from bot import CheckerClient, StatusMonitor, TelegramBot, Watcher, create_app


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


class TelegramUpdatesResponse:
    status_code = 200

    def __init__(self, updates):
        self.updates = updates

    def raise_for_status(self):
        return None

    def json(self):
        return {"ok": True, "result": self.updates}


class TelegramPayloadResponse(TelegramUpdatesResponse):
    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


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


# Bug caught: an object-valued checker status raises or becomes a usable remote state.
def test_object_checker_status_becomes_server_unreachable():
    client = CheckerClient(
        "http://checker/api/v1/status",
        "secret",
        10,
        lambda *args, **kwargs: FakeResponse(200, {"status": {}}),
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


# Bug caught: every poll is announced, or a real effective-status transition is missed.
def test_watcher_notifies_only_when_effective_status_changes():
    monitor = Mock()
    monitor.refresh.side_effect = ["running", "running", "license_expired"]
    send_message = Mock()
    watcher = Watcher(
        monitor,
        ["123456789"],
        {"running": "Container is UP", "license_expired": "License expired"},
        send_message,
        notify_on_start=True,
    )

    watcher.check_once()
    watcher.check_once()
    watcher.check_once()

    assert send_message.call_args_list == [
        call("Container is UP", "123456789"),
        call("License expired", "123456789"),
    ]


# Bug caught: /ts_status reports an empty cache instead of fetching the first status.
def test_ts_status_refreshes_before_reply_when_no_cached_status():
    monitor = Mock(current_status=None)
    monitor.get_status.return_value = None
    monitor.refresh.return_value = "running"
    send_message = Mock()
    telegram = TelegramBot(
        monitor,
        {"123456789"},
        {"running": "Container is currently running"},
        send_message,
    )

    telegram.handle_command("/ts_status", "123456789")

    assert send_message.call_args == call(
        "Container is currently running", "123456789"
    )


# Bug caught: notify_on_start=false still broadcasts the first observed status.
def test_watcher_suppresses_initial_notification_when_disabled():
    monitor = Mock()
    monitor.refresh.side_effect = ["running", "stopped"]
    send_message = Mock()
    watcher = Watcher(
        monitor,
        ["123456789"],
        {"running": "UP", "stopped": "DOWN"},
        send_message,
        notify_on_start=False,
    )

    watcher.check_once()
    watcher.check_once()

    assert send_message.call_args_list == [call("DOWN", "123456789")]


# Bug caught: Telegram long polling replays updates or accepts commands from unknown chats.
def test_telegram_poll_filters_chats_and_advances_update_offset():
    monitor = Mock(current_status="running")
    monitor.get_status.return_value = "running"
    send_message = Mock()
    observed = {}

    def recording_get(url, **kwargs):
        observed["url"] = url
        observed.update(kwargs)
        return TelegramUpdatesResponse(
            [
                {
                    "update_id": 40,
                    "message": {
                        "chat": {"id": 123456789},
                        "text": "/ts_status",
                    },
                },
                {
                    "update_id": 41,
                    "message": {
                        "chat": {"id": 987654321},
                        "text": "/ts_status",
                    },
                },
                {
                    "update_id": 42,
                    "message": {
                        "chat": {"id": 123456789},
                        "text": "hello",
                    },
                },
            ]
        )

    telegram = TelegramBot(
        monitor,
        {"123456789"},
        {"running": "Container is currently running"},
        send_message,
        api_base="https://api.telegram.org/botsecret",
        http_get=recording_get,
    )

    next_offset = telegram.poll_once(37)

    assert next_offset == 43
    assert observed == {
        "url": "https://api.telegram.org/botsecret/getUpdates",
        "params": {
            "timeout": 30,
            "allowed_updates": ["message"],
            "offset": 37,
        },
        "timeout": 35,
    }
    assert send_message.call_args_list == [
        call("Container is currently running", "123456789")
    ]


# Bug caught: /ts_status bypasses the monitor's lock-protected cache accessor.
def test_ts_status_reads_cached_status_through_monitor_accessor():
    monitor = Mock(spec=["get_status", "refresh"])
    monitor.get_status.return_value = "running"
    send_message = Mock()
    telegram = TelegramBot(
        monitor,
        {"123456789"},
        {"running": "Container is currently running"},
        send_message,
    )

    telegram.handle_command("/ts_status", "123456789")

    assert send_message.call_args == call(
        "Container is currently running", "123456789"
    )


# Bug caught: a non-object or API-error getUpdates payload kills the listener thread.
@pytest.mark.parametrize(
    "payload",
    [[], {"ok": False, "result": []}, {"ok": True, "result": [None]}],
)
def test_telegram_poll_rejects_invalid_api_payload_as_recoverable(payload):
    telegram = TelegramBot(
        Mock(current_status="running"),
        {"123456789"},
        {},
        Mock(),
        api_base="https://api.telegram.org/botsecret",
        http_get=lambda *args, **kwargs: TelegramPayloadResponse(payload),
    )

    with pytest.raises(ValueError, match="Telegram getUpdates payload"):
        telegram.poll_once(None)


# Bug caught: an unrelated command sharing the /ts_status prefix receives status data.
def test_ts_status_rejects_longer_unrelated_command():
    send_message = Mock()
    telegram = TelegramBot(
        Mock(current_status="running"),
        {"123456789"},
        {"running": "Container is currently running"},
        send_message,
    )

    telegram.handle_command("/ts_status_bad", "123456789")

    send_message.assert_not_called()
