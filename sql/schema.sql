-- Shared schema. Changes here affect everyone: announce them in the group chat.
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS sensor_events (
  event_id    TEXT PRIMARY KEY,
  node_id     TEXT NOT NULL,
  sensor      TEXT NOT NULL,
  value       REAL NOT NULL,
  unit        TEXT,
  observed_at REAL NOT NULL,      -- event time (wall clock, set by the sensor)
  received_at REAL                -- receipt time (set by the Processor)
);
CREATE INDEX IF NOT EXISTS idx_events_observed ON sensor_events(observed_at);

CREATE TABLE IF NOT EXISTS edge_decisions (
  decision_id   TEXT PRIMARY KEY,
  event_id      TEXT NOT NULL REFERENCES sensor_events(event_id),
  rule          TEXT,
  actuator      TEXT,
  command_value REAL,
  issued_mono   REAL,             -- time.monotonic(); only meaningful since last boot
  expires_mono  REAL,             -- issued_mono + ttl
  status        TEXT NOT NULL DEFAULT 'PENDING',   -- PENDING | DISPATCHED | EXPIRED
  created_at    REAL
);

CREATE TABLE IF NOT EXISTS outbox (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id    TEXT NOT NULL UNIQUE,
  payload     TEXT NOT NULL,
  enqueued_at REAL NOT NULL,
  sent_at     REAL                -- NULL = still waiting for the WAN
);
CREATE INDEX IF NOT EXISTS idx_outbox_pending ON outbox(sent_at);

CREATE TABLE IF NOT EXISTS process_health (
  name            TEXT PRIMARY KEY,
  pid             INTEGER,
  state           TEXT,
  rss_kb          INTEGER,
  cpu_pct         REAL,
  ctx_voluntary   INTEGER,
  ctx_involuntary INTEGER,
  restarts        INTEGER,
  updated_at      REAL
);

-- Mock upstream receiver. PRIMARY KEY on event_id gives idempotent delivery.
CREATE TABLE IF NOT EXISTS upstream_sink (
  event_id    TEXT PRIMARY KEY,
  payload     TEXT NOT NULL,
  received_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS kv (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
