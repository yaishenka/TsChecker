import os
import time
import threading
import yaml
import docker
import requests

CONFIG_PATH = os.environ.get("CONFIG_PATH", "./config.yaml")

with open(CONFIG_PATH) as f:
    config = yaml.safe_load(f)

CONTAINER_NAME = config["container_name"]
TG = config["telegram"]
BOT_TOKEN = TG["bot_token"]
CHAT_IDS = set(str(c) for c in TG["chat_ids"])
POLL_INTERVAL = int(TG.get("poll_interval", 3600))
NOTIFY_ON_START = bool(TG.get("notify_on_start", False))
MESSAGES = TG.get("messages", {})

API_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"

docker_client = docker.from_env()


def get_container_status():
    try:
        return docker_client.containers.get(CONTAINER_NAME).status
    except docker.errors.NotFound:
        return "not_found"


def send_to_chat(text, chat_id):
    try:
        resp = requests.post(f"{API_BASE}/sendMessage", json={"chat_id": chat_id, "text": text}, timeout=10)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"[telegram] failed to send to {chat_id}: {e}")


def broadcast(text):
    for chat_id in CHAT_IDS:
        send_to_chat(text, chat_id)


def status_message(status):
    return MESSAGES.get(status, f"Status: {status}")


def command_listener():
    offset = None
    print("[commands] listening for /ts_status")
    while True:
        try:
            params = {"timeout": 30, "allowed_updates": ["message"]}
            if offset is not None:
                params["offset"] = offset
            resp = requests.get(f"{API_BASE}/getUpdates", params=params, timeout=35)
            resp.raise_for_status()
            for update in resp.json().get("result", []):
                offset = update["update_id"] + 1
                msg = update.get("message", {})
                chat_id = str(msg.get("chat", {}).get("id", ""))
                text = msg.get("text", "")
                if chat_id in CHAT_IDS and text.startswith("/ts_status"):
                    status = get_container_status()
                    print(f"[commands] /ts_status requested by chat {chat_id}, status={status}")
                    send_to_chat(status_message(status), chat_id)
        except requests.RequestException as e:
            print(f"[commands] request error: {e}")
            time.sleep(5)
        except Exception as e:
            print(f"[commands] unexpected error: {e}")
            time.sleep(5)


def monitor_loop():
    previous_status = None
    print(f"[monitor] watching '{CONTAINER_NAME}', interval {POLL_INTERVAL}s")

    if NOTIFY_ON_START and "started" in MESSAGES:
        broadcast(MESSAGES["started"])

    while True:
        status = get_container_status()

        if status != previous_status:
            print(f"[monitor] status changed: {previous_status!r} -> {status!r}")
            if previous_status is not None or NOTIFY_ON_START:
                broadcast(status_message(status))
            previous_status = status

        time.sleep(POLL_INTERVAL)


def main():
    t = threading.Thread(target=command_listener, daemon=True)
    t.start()
    monitor_loop()


if __name__ == "__main__":
    main()
