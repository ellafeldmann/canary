CREATE TABLE IF NOT EXISTS sources (
  id TEXT PRIMARY KEY,
  label TEXT NOT NULL,
  cadence_minutes INTEGER NOT NULL
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

CREATE TABLE IF NOT EXISTS alerts (
  id INTEGER PRIMARY KEY,
  source_id TEXT NOT NULL REFERENCES sources(id),
  event_id INTEGER REFERENCES events(id),
  triggered_at TEXT NOT NULL,
  severity REAL NOT NULL,
  message TEXT NOT NULL,
  delivered INTEGER DEFAULT 0
);

INSERT OR IGNORE INTO sources (id, label, cadence_minutes) VALUES
  ('usgs', 'USGS Earthquakes', 15),
  ('gdelt', 'GDELT Events', 30),
  ('fred', 'FRED Economic Series', 1440),
  ('noaa', 'NOAA Active Alerts', 15);
