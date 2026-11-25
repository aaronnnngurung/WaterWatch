
"""Test MQTT connectivity for the three WaterWatch devices."""

import logging
import os

from dotenv import load_dotenv

from communication.mqtt_client import WaterWatchMQTT

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

HOST = os.getenv(
    "THINGSBOARD_HOST",
    "mqtt.eu.thingsboard.cloud"
)

PORT = int(os.getenv("THINGSBOARD_PORT", "8883"))

DEVICES = {
    "Rasuwa": os.getenv("RASUWA_TOKEN"),
    "Trishuli": os.getenv("TRISHULI_TOKEN"),
    "Nuwakot": os.getenv("NUWAKOT_TOKEN"),
}


def run_test():
    clients = []

    try:
        for node_name, token in DEVICES.items():

            print(f"\nConnecting to {node_name}...")

            if not token:
                print(f"Missing access token for {node_name}")
                continue

            client = WaterWatchMQTT(
                node_name=node_name,
                access_token=token,
                host=HOST,
                port=PORT
            )

            if client.connect():
                print(f"{node_name}: CONNECTION SUCCESSFUL")
                clients.append(client)
            else:
                print(f"{node_name}: CONNECTION FAILED")

    finally:
        for client in clients:
            client.disconnect()

    print("\nMQTT connection test completed.")


if __name__ == "__main__":
    run_test()
