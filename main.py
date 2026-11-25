
"""WaterWatch - Main virtual edge monitoring application."""

import logging
import os
import signal
import time

from dotenv import load_dotenv

from config.nodes import NODES
from simulator.sensor_model import generate_reading
from simulator.contamination import ContaminationEvent

from database.sqlite_manager import SQLiteManager

from communication.mqtt_client import WaterWatchMQTT
from communication.sync_manager import SyncManager


# --------------------------------------------------
# CONFIGURATION
# --------------------------------------------------

load_dotenv()

SAMPLE_INTERVAL = 5

BASELINE_END = 20
CONTAMINATION_END = 60
OUTAGE_END = 90
DEMO_END = 120

BATCH_SIZE = 100

HOST = os.getenv(
    "THINGSBOARD_HOST",
    "mqtt.eu.thingsboard.cloud"
)

PORT = int(
    os.getenv("THINGSBOARD_PORT", "8883")
)


# --------------------------------------------------
# LOGGING CONFIGURATION
# --------------------------------------------------

os.makedirs("logs", exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    handlers=[
        logging.FileHandler("logs/waterwatch.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger("WaterWatch.Main")


# --------------------------------------------------
# APPLICATION STATE
# --------------------------------------------------

running = True


def stop_application(signum, frame):
    """Handle Ctrl+C safely."""

    global running

    logger.info("SHUTDOWN REQUESTED")
    running = False


signal.signal(signal.SIGINT, stop_application)


# --------------------------------------------------
# MQTT CLIENT CREATION
# --------------------------------------------------

def create_mqtt_clients():

    clients = {}

    for node_id, node in NODES.items():

        clients[node_id] = WaterWatchMQTT(
            node_name=node["name"],
            access_token=node["token"],
            host=HOST,
            port=PORT
        )

    return clients


# --------------------------------------------------
# SCENARIO MANAGEMENT
# --------------------------------------------------

def get_scenario(elapsed):

    if elapsed < BASELINE_END:
        return "BASELINE"

    if elapsed < CONTAMINATION_END:
        return "CONTAMINATION"

    if elapsed < OUTAGE_END:
        return "NETWORK_OUTAGE"

    if elapsed < DEMO_END:
        return "RECOVERY"

    return "NORMAL_MONITORING"


# --------------------------------------------------
# MAIN APPLICATION
# --------------------------------------------------

def main():

    global running

    logger.info("=" * 60)
    logger.info("WATERWATCH VIRTUAL EDGE SYSTEM STARTING")
    logger.info("=" * 60)

    # 1. Initialise SQLite.
    database = SQLiteManager()

    # 2. Create the three MQTT clients.
    mqtt_clients = create_mqtt_clients()

    # 3. Create the synchronisation manager.
    sync_manager = SyncManager(
        database=database,
        mqtt_clients=mqtt_clients,
        batch_size=BATCH_SIZE,
        sync_interval=SAMPLE_INTERVAL
    )

    # 4. Create the shared contamination event.
    contamination = ContaminationEvent(
        rise_seconds=20,
        washout_seconds=60
    )

    start_time = time.time()

    contamination_started = False
    outage_started = False
    recovery_started = False

    logger.info("MONITORING NODES: %s", len(NODES))

    # Initial MQTT connection attempts.
    for node_id, client in mqtt_clients.items():

        logger.info("CONNECTING NODE: %s", node_id)

        if not client.connect():
            logger.warning(
                "INITIAL CONNECTION FAILED | node=%s | "
                "readings will be buffered locally",
                node_id
            )

    logger.info("WATERWATCH MONITORING STARTED")

    try:

        while running:

            current_time = time.time()
            elapsed = current_time - start_time

            scenario = get_scenario(elapsed)

            # --------------------------------------
            # START CONTAMINATION EVENT
            # --------------------------------------

            if (
                scenario == "CONTAMINATION"
                and not contamination_started
            ):

                contamination.start(current_time)
                contamination_started = True

                logger.warning(
                    "SCENARIO STARTED | RAINFALL CONTAMINATION"
                )

            # --------------------------------------
            # SIMULATE NETWORK OUTAGE
            # --------------------------------------

            if (
                scenario == "NETWORK_OUTAGE"
                and not outage_started
            ):

                logger.warning(
                    "NETWORK OUTAGE STARTED | "
                    "disconnecting all MQTT nodes"
                )

                for client in mqtt_clients.values():
                    client.disconnect()

                outage_started = True

            # --------------------------------------
            # NETWORK RECOVERY
            # --------------------------------------

            if (
                scenario == "RECOVERY"
                and not recovery_started
            ):

                logger.warning(
                    "NETWORK RESTORED | "
                    "starting buffered telemetry replay"
                )

                recovery_started = True

            # --------------------------------------
            # GENERATE AND STORE TELEMETRY
            # --------------------------------------

            if scenario == "CONTAMINATION":

                event_intensity = contamination.get_intensity(
                    current_time
                )

            elif scenario == "NETWORK_OUTAGE":

                event_intensity = contamination.get_intensity(
                    current_time
                )

            else:

                event_intensity = 0.0

            for node_id, node in NODES.items():

                reading = generate_reading(
                    node=node,
                    event_intensity=event_intensity,
                    current_time=current_time
                )

                # IMPORTANT:
                # Always store before attempting MQTT delivery.
                database.insert_reading(
                    node_id=node_id,
                    payload=reading
                )

                logger.info(
                    "TELEMETRY GENERATED | node=%s | "
                    "pH=%.2f | turbidity=%.1f NTU | "
                    "TDS=%s ppm | temperature=%.1f C | "
                    "flow=%.1f L/min",
                    node_id,
                    reading["ph"],
                    reading["turbidity_ntu"],
                    reading["tds_ppm"],
                    reading["water_temp_c"],
                    reading["flow_lpm"]
                )

            # --------------------------------------
            # SYNCHRONISE WHEN NETWORK IS AVAILABLE
            # --------------------------------------

            if scenario != "NETWORK_OUTAGE":

                synced = sync_manager.sync_once()

                if synced > 0:

                    logger.info(
                        "TELEMETRY SYNCHRONISED | count=%s",
                        synced
                    )

            else:

                logger.warning(
                    "OFFLINE BUFFERING | pending=%s",
                    database.get_pending_count()
                )

            # --------------------------------------
            # PERIODIC SYSTEM STATUS
            # --------------------------------------

            if int(elapsed) % 15 < SAMPLE_INTERVAL:

                stats = database.get_statistics()

                logger.info(
                    "SYSTEM STATUS | scenario=%s | "
                    "total=%s | pending=%s | synced=%s | "
                    "evicted=%s",
                    scenario,
                    stats["total_readings"],
                    stats["pending_readings"],
                    stats["synced_readings"],
                    stats["evicted_readings"]
                )

            time.sleep(SAMPLE_INTERVAL)

    except Exception:

        logger.exception("UNEXPECTED APPLICATION ERROR")

        raise

    finally:

        logger.info("SHUTTING DOWN WATERWATCH")

        for client in mqtt_clients.values():
            client.disconnect()

        final_stats = database.get_statistics()

        logger.info("FINAL DATABASE STATISTICS: %s", final_stats)

        logger.info("WATERWATCH STOPPED")


if __name__ == "__main__":
    main()
