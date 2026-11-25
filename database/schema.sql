
-- WaterWatch SQLite database schema

CREATE TABLE IF NOT EXISTS telemetry (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id TEXT NOT NULL,
    timestamp_ms INTEGER NOT NULL,
    payload_json TEXT NOT NULL,
    synced INTEGER NOT NULL DEFAULT 0
        CHECK (synced IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Supports chronological retrieval of unsynchronised readings.
CREATE INDEX IF NOT EXISTS idx_telemetry_pending
ON telemetry (synced, timestamp_ms, id);

-- Supports per-node history and diagnostics.
CREATE INDEX IF NOT EXISTS idx_telemetry_node
ON telemetry (node_id, timestamp_ms);

-- Records buffer evictions and other buffer-management events.
CREATE TABLE IF NOT EXISTS buffer_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    node_id TEXT,
    telemetry_id INTEGER,
    event_details TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
