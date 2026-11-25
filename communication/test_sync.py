
"""Test SQLite-to-ThingsBoard synchronisation."""

import logging
import os

from dotenv import load_dotenv

from config.nodes import NODES
from database.sqlite_manager import SQLiteManager
from communication.mqtt_client import WaterWatchMQTT
from communication.sync_manager import SyncManager

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)


def main():

    database = SQLiteManager()

    clients = {}

    for node_id, node in NODES.items():

        clients[node_id] = WaterWatchMQTT(
            node_name=node["name"],
            access_token=node["token"],
            host=os.getenv(
                "THINGSBOARD_HOST",
                "mqtt.eu.thingsboard.cloud"
            ),
            port=int(os.getenv("THINGSBOARD_PORT", "8883"))
        )

    sync_manager = SyncManager(
        database=database,
        mqtt_clients=clients,
        batch_size=100,
        sync_interval=5
    )

    try:
        print("\nStarting WaterWatch synchronisation test...")

        print(
            "Pending readings:",
            database.get_pending_count()
        )

        # Process one batch for testing.
        synced = sync_manager.sync_once()

        print("\nSynchronisation test completed.")
        print("Readings synchronised:", synced)
        print(
            "Remaining pending readings:",
            database.get_pending_count()
        )

    finally:
        for client in clients.values():
            client.disconnect()


if __name__ == "__main__":
    main()
