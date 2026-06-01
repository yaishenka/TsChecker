import os
import time
import yaml
import docker
import requests

CONFIG_PATH = os.environ.get("CONFIG_PATH", "./config.yaml")

with open(CONFIG_PATH) as f:
    config = yaml.safe_load(f)

CONTAINER_NAME = config["container_name"]
TG = config["telegram"]
BOT_TOKEN = TG["bot_token"]
CHAT_ID = TG["chat_id"]
POLL_INTERVAL = int(TG.get("poll_interval", 3600))
MESSAGES = TG.get("messages", {})

TELEGRAM_URL = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"


def get_container_status(client):
    try:
        return client.containers.get(CONTAINER_NAME).status
    except docker.errors.NotFound:
        return "not_found"


def send_telegram(status):
    text = MESSAGES.get(status, f"Status: {status}")
    try:
        resp = requests.post(TELEGRAM_URL, json={"chat_id": CHAT_ID, "text": text}, timeout=10)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"[telegram] failed to send message: {e}")


def main():
    client = docker.from_env()
    previous_status = None

    print(f"[bot] watching container '{CONTAINER_NAME}', poll interval {POLL_INTERVAL}s")

    while True:
        status = get_container_status(client)

        if status != previous_status:
            print(f"[bot] status changed: {previous_status!r} -> {status!r}")
            if previous_status is not None:
                send_telegram(status)
            previous_status = status

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
