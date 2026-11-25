
"""SQLite storage and store-and-forward buffer for WaterWatch."""

import json
import logging
import sqlite3
import threading

from pathlib import Path
from contextlib import closing

logger = logging.getLogger("WaterWatch.Database")

DATABASE_PATH = Path(__file__).resolve().parent / "waterwatch.db"
SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"

DEFAULT_MAX_BUFFER_SIZE = 100_000


class SQLiteManager:
    """Manage persistent telemetry storage and pending MQTT messages."""

    def __init__(
        self,
        database_path=DATABASE_PATH,
        max_buffer_size=DEFAULT_MAX_BUFFER_SIZE
    ):
        if max_buffer_size < 1:
            raise ValueError("Maximum buffer size must be at least 1.")

        self.database_path = str(database_path)
        self.max_buffer_size = max_buffer_size
        self.lock = threading.Lock()

        self.initialize_database()

    def _connect(self):
        """Create a connection with a reasonable wait for database locks."""

        connection = sqlite3.connect(
            self.database_path,
            timeout=30
        )
        connection.row_factory = sqlite3.Row
        return connection

    def initialize_database(self):
        """Create database tables and enable WAL mode."""

        schema = SCHEMA_PATH.read_text(encoding="utf-8")

        with closing(self._connect()) as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=NORMAL")
            connection.executescript(schema)
            connection.commit()

        logger.info(
            "SQLite database initialized: %s",
            self.database_path
        )
        logger.info("SQLite Write-Ahead Logging enabled.")

    def _record_event(
        self,
        connection,
        event_type,
        node_id=None,
        telemetry_id=None,
        details=None
    ):
        """Record buffer-management events."""

        connection.execute(
            """
            INSERT INTO buffer_events
            (event_type, node_id, telemetry_id, event_details)
            VALUES (?, ?, ?, ?)
            """,
            (event_type, node_id, telemetry_id, details)
        )

    def insert_reading(self, node_id, payload):
        """
        Store a reading before attempting MQTT publishing.

        If the pending buffer is full, evict the oldest pending
        reading to make room for the newest reading.

        Returns the new database row ID.
        """

        if "ts" not in payload:
            raise ValueError("Telemetry payload must contain 'ts'.")

        timestamp_ms = int(payload["ts"])
        payload_json = json.dumps(payload, separators=(",", ":"))

        with self.lock:
            connection = self._connect()

            try:
                connection.execute("BEGIN IMMEDIATE")

                pending_count = connection.execute(
                    """
                    SELECT COUNT(*)
                    FROM telemetry
                    WHERE synced = 0
                    """
                ).fetchone()[0]

                if pending_count >= self.max_buffer_size:

                    oldest = connection.execute(
                        """
                        SELECT id, node_id
                        FROM telemetry
                        WHERE synced = 0
                        ORDER BY timestamp_ms ASC, id ASC
                        LIMIT 1
                        """
                    ).fetchone()

                    if oldest:
                        connection.execute(
                            "DELETE FROM telemetry WHERE id = ?",
                            (oldest["id"],)
                        )

                        self._record_event(
                            connection,
                            event_type="BUFFER_EVICTION",
                            node_id=oldest["node_id"],
                            telemetry_id=oldest["id"],
                            details=(
                                "Oldest pending reading evicted "
                                "to preserve newer monitoring data."
                            )
                        )

                        logger.warning(
                            "Buffer full. Evicted oldest reading ID %s.",
                            oldest["id"]
                        )

                cursor = connection.execute(
                    """
                    INSERT INTO telemetry
                    (node_id, timestamp_ms, payload_json, synced)
                    VALUES (?, ?, ?, 0)
                    """,
                    (node_id, timestamp_ms, payload_json)
                )

                reading_id = cursor.lastrowid

                connection.commit()

                logger.info(
                    "STORED | node=%s | id=%s | timestamp=%s",
                    node_id,
                    reading_id,
                    timestamp_ms
                )

            except Exception:
                connection.rollback()
                raise

            finally:
                connection.close()

        self.log_buffer_depth()

        return reading_id

    def get_pending_batch(self, batch_size=100):
        """Retrieve pending readings in chronological order."""

        if batch_size < 1:
            raise ValueError("Batch size must be at least 1.")

        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT id, node_id, timestamp_ms, payload_json
                FROM telemetry
                WHERE synced = 0
                ORDER BY timestamp_ms ASC, id ASC
                LIMIT ?
                """,
                (batch_size,)
            ).fetchall()

        return [
            {
                "id": row["id"],
                "node_id": row["node_id"],
                "timestamp_ms": row["timestamp_ms"],
                "payload": json.loads(row["payload_json"])
            }
            for row in rows
        ]

    def mark_synced(self, reading_ids):
        """
        Mark readings as synced after confirmed MQTT delivery.
        """

        if not reading_ids:
            return 0

        updated = 0

        with self.lock:
            connection = self._connect()

            try:
                connection.execute("BEGIN IMMEDIATE")

                for reading_id in reading_ids:
                    cursor = connection.execute(
                        """
                        UPDATE telemetry
                        SET synced = 1
                        WHERE id = ? AND synced = 0
                        """,
                        (reading_id,)
                    )

                    updated += cursor.rowcount

                connection.commit()

            except Exception:
                connection.rollback()
                raise

            finally:
                connection.close()

        logger.info("SYNCED | %s readings confirmed.", updated)

        self.log_buffer_depth()

        return updated

    def get_pending_count(self):
        """Return the number of unsynchronised readings."""

        with closing(self._connect()) as connection:
            count = connection.execute(
                """
                SELECT COUNT(*)
                FROM telemetry
                WHERE synced = 0
                """
            ).fetchone()[0]

        return count

    def get_total_count(self):
        """Return the total number of stored readings."""

        with closing(self._connect()) as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM telemetry"
            ).fetchone()[0]

        return count

    def get_synced_count(self):
        """Return the number of synchronised readings."""

        with closing(self._connect()) as connection:
            count = connection.execute(
                """
                SELECT COUNT(*)
                FROM telemetry
                WHERE synced = 1
                """
            ).fetchone()[0]

        return count

    def get_eviction_count(self):
        """Return the total number of recorded buffer evictions."""

        with closing(self._connect()) as connection:
            count = connection.execute(
                """
                SELECT COUNT(*)
                FROM buffer_events
                WHERE event_type = 'BUFFER_EVICTION'
                """
            ).fetchone()[0]

        return count

    def log_buffer_depth(self):
        """Log the current number of pending readings."""

        depth = self.get_pending_count()

        logger.info(
            "BUFFER DEPTH | %s / %s pending readings",
            depth,
            self.max_buffer_size
        )

        return depth

    def get_statistics(self):
        """Return database and buffer statistics."""

        return {
            "total_readings": self.get_total_count(),
            "pending_readings": self.get_pending_count(),
            "synced_readings": self.get_synced_count(),
            "evicted_readings": self.get_eviction_count(),
            "maximum_buffer_size": self.max_buffer_size,
        }
