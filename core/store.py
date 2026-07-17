import json
import os
from pathlib import Path

import libsql

_SCHEMA_PATH = Path(__file__).resolve().parent.parent / "db" / "schema.sql"


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


def has_alert_for_event(conn, event_id):
    row = conn.execute("SELECT 1 FROM alerts WHERE event_id = ?", (event_id,)).fetchone()
    return row is not None


def record_alert(conn, *, source_id, event_id, triggered_at, severity, message, delivered):
    conn.execute(
        """
        INSERT INTO alerts (source_id, event_id, triggered_at, severity, message, delivered)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (source_id, event_id, triggered_at, severity, message, int(delivered)),
    )
    conn.commit()
