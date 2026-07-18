import json
import os
from pathlib import Path

import libsql

from core.geo import haversine_km

_SCHEMA_PATH = Path(__file__).resolve().parent.parent / "db" / "schema.sql"


def _column_exists(conn, table, column):
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(row[1] == column for row in rows)


def _migrate(conn):
    # CREATE TABLE IF NOT EXISTS silently no-ops against a table that already
    # exists from a prior deploy, so new columns on existing tables need an
    # explicit, idempotency-checked ALTER rather than relying on schema.sql alone.
    if not _column_exists(conn, "sources", "geo_scope"):
        conn.execute("ALTER TABLE sources ADD COLUMN geo_scope TEXT")
        conn.execute("UPDATE sources SET geo_scope = 'point' WHERE id IN ('usgs', 'noaa')")
        conn.execute("UPDATE sources SET geo_scope = 'country' WHERE id IN ('gdelt', 'fred')")

    if not _column_exists(conn, "alerts", "subscriber_id"):
        conn.execute("ALTER TABLE alerts ADD COLUMN subscriber_id INTEGER REFERENCES subscribers(id)")

    conn.commit()


def _seed_sources(conn):
    # Run only after _migrate(), so geo_scope is guaranteed to exist by now
    # regardless of whether this is a fresh db or one forward-migrated from Phase 1.
    conn.executemany(
        "INSERT OR IGNORE INTO sources (id, label, cadence_minutes, geo_scope) VALUES (?, ?, ?, ?)",
        [
            ("usgs", "USGS Earthquakes", 15, "point"),
            ("gdelt", "GDELT Events", 30, "country"),
            ("fred", "FRED Economic Series", 1440, "country"),
            ("noaa", "NOAA Active Alerts", 15, "point"),
        ],
    )
    conn.commit()


def get_connection():
    url = os.environ.get("TURSO_DATABASE_URL") or "file:local.db"
    token = os.environ.get("TURSO_AUTH_TOKEN") or None

    if os.environ.get("GITHUB_ACTIONS") and url == "file:local.db":
        raise RuntimeError(
            "TURSO_DATABASE_URL is missing or empty in this workflow run. "
            "Without it, writes silently land in a throwaway local database "
            "instead of Turso. Check the repo's Actions secrets."
        )

    conn = libsql.connect(database=url, auth_token=token) if token else libsql.connect(database=url)
    conn.executescript(_SCHEMA_PATH.read_text())
    conn.commit()
    _migrate(conn)
    _seed_sources(conn)
    return conn


def upsert_event(conn, *, source_id, external_id, occurred_at, region, severity, payload):
    conn.execute(
        """
        INSERT INTO events (source_id, external_id, occurred_at, region, severity, payload_json)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT (source_id, external_id) DO UPDATE SET
          occurred_at = excluded.occurred_at,
          region = excluded.region,
          severity = excluded.severity,
          payload_json = excluded.payload_json
        """,
        (source_id, external_id, occurred_at, region, severity, json.dumps(payload)),
    )
    conn.commit()
    row = conn.execute(
        "SELECT id FROM events WHERE source_id = ? AND external_id = ?",
        (source_id, external_id),
    ).fetchone()
    return row[0]


def find_matching_subscribers(conn, *, source_id, event_severity, region=None, lat=None, lon=None):
    geo_scope = conn.execute("SELECT geo_scope FROM sources WHERE id = ?", (source_id,)).fetchone()[0]

    rows = conn.execute(
        """
        SELECT s.id, s.telegram_chat_id, sl.lat, sl.lon, sl.radius_km, sl.country_code
        FROM subscribers s
        JOIN subscriber_locations sl ON sl.subscriber_id = s.id
        WHERE s.active = 1 AND s.min_severity <= ? AND sl.scope_type = ?
        """,
        (event_severity, geo_scope),
    ).fetchall()

    matched = {}
    for subscriber_id, chat_id, loc_lat, loc_lon, radius_km, country_code in rows:
        if subscriber_id in matched:
            continue  # one alert per subscriber even if several of their locations match

        if geo_scope == "point":
            if lat is None or lon is None or loc_lat is None or loc_lon is None:
                continue
            if haversine_km(lat, lon, loc_lat, loc_lon) <= radius_km:
                matched[subscriber_id] = chat_id
        else:  # country
            if region and country_code and region.upper() == country_code.upper():
                matched[subscriber_id] = chat_id

    return list(matched.items())


def has_alert_for_subscriber(conn, event_id, subscriber_id):
    row = conn.execute(
        "SELECT 1 FROM alerts WHERE event_id = ? AND subscriber_id = ?",
        (event_id, subscriber_id),
    ).fetchone()
    return row is not None


def record_alert(conn, *, source_id, event_id, subscriber_id, triggered_at, severity, message, delivered):
    conn.execute(
        """
        INSERT INTO alerts (source_id, event_id, subscriber_id, triggered_at, severity, message, delivered)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (source_id, event_id, subscriber_id, triggered_at, severity, message, int(delivered)),
    )
    conn.commit()
