CREATE TABLE IF NOT EXISTS sources (
  id TEXT PRIMARY KEY,
  label TEXT NOT NULL,
  cadence_minutes INTEGER NOT NULL,
  geo_scope TEXT NOT NULL CHECK (geo_scope IN ('point', 'country'))
  -- point: usgs, noaa (lat/lon + radius match) · country: gdelt, fred (exact match)
);

-- scalar time series: FRED series, GDELT daily aggregates, NOAA alert counts
CREATE TABLE IF NOT EXISTS readings (
  id INTEGER PRIMARY KEY,
  source_id TEXT NOT NULL REFERENCES sources(id),
  fetched_at TEXT NOT NULL,
  metric TEXT NOT NULL,
  region TEXT,
  raw_value REAL,
  severity REAL,
  meta_json TEXT
);

-- discrete events: individual earthquakes, individual NOAA alerts
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY,
  source_id TEXT NOT NULL REFERENCES sources(id),
  external_id TEXT NOT NULL,
  occurred_at TEXT NOT NULL,
  region TEXT,
  severity REAL NOT NULL,
  payload_json TEXT NOT NULL,
  UNIQUE (source_id, external_id)
);

CREATE TABLE IF NOT EXISTS baselines (
  source_id TEXT NOT NULL REFERENCES sources(id),
  metric TEXT NOT NULL,
  region TEXT,
  window_start TEXT NOT NULL,
  mean REAL,
  stddev REAL,
  PRIMARY KEY (source_id, metric, region, window_start)
);

-- one row per person, one Telegram chat each
CREATE TABLE IF NOT EXISTS subscribers (
  id INTEGER PRIMARY KEY,
  telegram_chat_id TEXT NOT NULL UNIQUE,
  min_severity REAL NOT NULL DEFAULT 3,
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL
);

-- up to 5 rows per subscriber (enforced below), mixed point/country freely
CREATE TABLE IF NOT EXISTS subscriber_locations (
  id INTEGER PRIMARY KEY,
  subscriber_id INTEGER NOT NULL REFERENCES subscribers(id),
  scope_type TEXT NOT NULL CHECK (scope_type IN ('point', 'country')),
  label TEXT,               -- human-readable, e.g. "Portland, OR"
  lat REAL,                 -- scope_type = 'point'
  lon REAL,                 -- scope_type = 'point'
  radius_km REAL,           -- scope_type = 'point'
  country_code TEXT,        -- scope_type = 'country'
  created_at TEXT NOT NULL
);

CREATE TRIGGER IF NOT EXISTS limit_subscriber_locations
BEFORE INSERT ON subscriber_locations
WHEN (SELECT COUNT(*) FROM subscriber_locations WHERE subscriber_id = NEW.subscriber_id) >= 5
BEGIN
  SELECT RAISE(ABORT, 'max 5 locations per subscriber');
END;

-- SQLite's own ON DELETE CASCADE needs "PRAGMA foreign_keys = ON" set on
-- every connection that touches this db, in every client (Python now, a
-- JS Worker later) -- one client that forgets it means cascade silently
-- stops happening. A trigger fires unconditionally instead.
CREATE TRIGGER IF NOT EXISTS cascade_delete_subscriber
AFTER DELETE ON subscribers
BEGIN
  DELETE FROM subscriber_locations WHERE subscriber_id = OLD.id;
  UPDATE alerts SET subscriber_id = NULL WHERE subscriber_id = OLD.id;
END;

CREATE TABLE IF NOT EXISTS alerts (
  id INTEGER PRIMARY KEY,
  source_id TEXT NOT NULL REFERENCES sources(id),
  event_id INTEGER REFERENCES events(id),          -- null for readings-based alerts
  subscriber_id INTEGER REFERENCES subscribers(id), -- null = pipeline/operator-level alert
  triggered_at TEXT NOT NULL,
  severity REAL NOT NULL,
  message TEXT NOT NULL,
  delivered INTEGER DEFAULT 0
);
