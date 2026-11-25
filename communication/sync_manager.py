
"""Store-and-forward synchronisation manager for WaterWatch."""

import logging
import threading
import time

logger = logging.getLogger("WaterWatch.Sync")


class SyncManager:
    """
    Replay pending SQLite telemetry to ThingsBoard.

    Each node has its own MQTT client and device access token.
    """

    def __init__(
        self,
        database,
        mqtt_clients,
        batch_size=100,
        sync_interval=5,
        initial_backoff=2,
        maximum_backoff=60
    ):
        self.database = database
        self.mqtt_clients = mqtt_clients
        self.batch_size = batch_size
        self.sync_interval = sync_interval
        self.initial_backoff = initial_backoff
        self.maximum_backoff = maximum_backoff

        self.stop_event = threading.Event()
        self.worker_thread = None

        # Keep separate retry delays for each monitoring node.
        self.retry_delays = {
            node_id: initial_backoff
            for node_id in mqtt_clients
        }

    def _connect_node(self, node_id, client):
        """Connect a node using exponential retry backoff."""

        if client.connected.is_set():
            return True

        delay = self.retry_delays[node_id]

        logger.warning(
            "RECONNECTING | node=%s | next retry delay=%s seconds",
            node_id,
            delay
        )

        if client.connect():
            self.retry_delays[node_id] = self.initial_backoff

            logger.info(
                "NODE ONLINE | node=%s",
                node_id
            )

            return True

        self.retry_delays[node_id] = min(
            delay * 2,
            self.maximum_backoff
        )

        logger.warning(
            "NODE OFFLINE | node=%s | retry in %s seconds",
            node_id,
            self.retry_delays[node_id]
        )

        return False

    def sync_once(self):
        """
        Process one batch of pending readings.

        Readings are fetched in chronological order. A row is marked
        synced only after its MQTT publish is acknowledged.
        """

        pending = self.database.get_pending_batch(
            batch_size=self.batch_size
        )

        if not pending:
            return 0

        logger.info(
            "SYNC STARTED | pending batch size=%s",
            len(pending)
        )

        synced_ids = []

        for reading in pending:

            if self.stop_event.is_set():
                break

            node_id = reading["node_id"]
            reading_id = reading["id"]
            payload = reading["payload"]

            client = self.mqtt_clients.get(node_id)

            if client is None:
                logger.error(
                    "UNKNOWN NODE | node=%s | reading_id=%s",
                    node_id,
                    reading_id
                )
                break

            # Reconnect before attempting to publish.
            if not self._connect_node(node_id, client):
                # Stop here to preserve chronological replay order.
                break

            logger.info(
                "REPLAYING | node=%s | reading_id=%s | timestamp=%s",
                node_id,
                reading_id,
                reading["timestamp_ms"]
            )

            delivered = client.publish_reading(payload)

            if not delivered:
                logger.warning(
                    "REPLAY FAILED | node=%s | reading_id=%s",
                    node_id,
                    reading_id
                )
                break

            synced_ids.append(reading_id)

            # Persist the confirmation immediately.
            self.database.mark_synced([reading_id])

        logger.info(
            "SYNC BATCH COMPLETED | confirmed=%s | remaining=%s",
            len(synced_ids),
            self.database.get_pending_count()
        )

        return len(synced_ids)

    def _worker(self):
        """Background worker for continuous synchronisation."""

        logger.info("SYNC WORKER STARTED")

        while not self.stop_event.is_set():

            try:
                synced_count = self.sync_once()

                if synced_count == 0:
                    self.stop_event.wait(self.sync_interval)

            except Exception:
                logger.exception(
                    "SYNC WORKER ERROR | will retry after interval"
                )
                self.stop_event.wait(self.sync_interval)

        logger.info("SYNC WORKER STOPPED")

    def start(self):
        """Start synchronisation in a background thread."""

        if self.worker_thread and self.worker_thread.is_alive():
            logger.warning("SYNC WORKER IS ALREADY RUNNING")
            return

        self.stop_event.clear()

        self.worker_thread = threading.Thread(
            target=self._worker,
            name="WaterWatch-Sync",
            daemon=True
        )

        self.worker_thread.start()

    def stop(self):
        """Stop the background synchronisation worker."""

        self.stop_event.set()

        if self.worker_thread:
            self.worker_thread.join(timeout=10)

        logger.info("SYNC MANAGER STOPPED")
