import argparse
import logging
import os

import requests

log = logging.getLogger(__name__)

_API = "https://api.telegram.org/bot{token}/sendMessage"


def send_telegram(message: str) -> bool:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        log.warning("no Telegram credentials set, skipping send: %s", message)
        return False

    resp = requests.post(
        _API.format(token=token),
        json={"chat_id": chat_id, "text": message},
        timeout=10,
    )
    resp.raise_for_status()
    return True


def notify_pipeline_error(message: str) -> bool:
    return send_telegram(f"⚠️ pipeline: {message}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument("--pipeline-error", metavar="MESSAGE")
    args = parser.parse_args()
    if args.pipeline_error:
        notify_pipeline_error(args.pipeline_error)
