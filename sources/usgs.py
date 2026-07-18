import datetime as dt
import logging

import requests
import yaml

from core import store
from core.alert import send_telegram
from core.severity import usgs_severity

log = logging.getLogger(__name__)

SOURCE_ID = "usgs"


def _load_config():
    with open("config.yml") as f:
        full = yaml.safe_load(f)
    return full["sources"]["usgs"]


def _iso(ms_epoch):
    return dt.datetime.fromtimestamp(ms_epoch / 1000, tz=dt.timezone.utc).isoformat()


def fetch_features(feed_url):
    resp = requests.get(feed_url, timeout=15)
    resp.raise_for_status()
    return resp.json()["features"]


def run():
    config = _load_config()
    conn = store.get_connection()

    features = fetch_features(config["feed_url"])
    log.info("fetched %d USGS features", len(features))

    for feature in features:
        props = feature["properties"]
        severity = usgs_severity(props, config)
        external_id = feature["id"]
        lon, lat = feature["geometry"]["coordinates"][:2]

        event_id = store.upsert_event(
            conn,
            source_id=SOURCE_ID,
            external_id=external_id,
            occurred_at=_iso(props["time"]),
            region=props.get("place"),
            severity=severity,
            payload={
                "mag": props.get("mag"),
                "place": props.get("place"),
                "alert": props.get("alert"),
                "sig": props.get("sig"),
                "tsunami": props.get("tsunami"),
                "lat": lat,
                "lon": lon,
                "url": props.get("url"),
            },
        )

        matches = store.find_matching_subscribers(
            conn, source_id=SOURCE_ID, event_severity=severity, lat=lat, lon=lon
        )
        if not matches:
            continue

        message = (
            f"🌍 M{props.get('mag')} — {props.get('place')}\n"
            f"severity {severity:.0f}/5 · {props.get('url')}"
        )

        for subscriber_id, chat_id in matches:
            if store.has_alert_for_subscriber(conn, event_id, subscriber_id):
                continue
            delivered = send_telegram(message, chat_id=chat_id)
            store.record_alert(
                conn,
                source_id=SOURCE_ID,
                event_id=event_id,
                subscriber_id=subscriber_id,
                triggered_at=dt.datetime.now(tz=dt.timezone.utc).isoformat(),
                severity=severity,
                message=message,
                delivered=delivered,
            )
            log.info(
                "alert sent for event %s to subscriber %s (severity %.0f)",
                external_id, subscriber_id, severity,
            )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run()
