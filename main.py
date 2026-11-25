"""WaterWatch - Main virtual edge monitoring application."""

import json
import logging
import os
import signal
import time
from pathlib import Path

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

# Scenario timeline (seconds since start)
BASELINE_END = 20              # 0-20     normal water conditions
CONTAMINATION_END = 60         # 20-60    rainfall contamination
OUTAGE_END = 90                # 60-90    network outage, readings buffered
RECOVERY_END = 105             # 90-105   network recovery, buffered replay
SUPPLY_INTERRUPTION_END = 115  # 105-115  supply interruption
DEMO_END = 130                 # 115-130  normal monitoring, then STOP

TIMELINE = [
    ("BASELINE", 0, BASELINE_END),
    ("CONTAMINATION", BASELINE_END, CONTAMINATION_END),
    ("NETWORK_OUTAGE", CONTAMINATION_END, OUTAGE_END),
    ("RECOVERY", OUTAGE_END, RECOVERY_END),
    ("SUPPLY_INTERRUPTION", RECOVERY_END, SUPPLY_INTERRUPTION_END),
    ("NORMAL_MONITORING", SUPPLY_INTERRUPTION_END, DEMO_END),
]

# Status file read by streamlit_app.py to show the current phase.
# Assumes main.py and streamlit_app.py sit in the same project folder.
STATE_PATH = Path(__file__).resolve().parent / "database" / "scenario_state.json"

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

    if elapsed < RECOVERY_END:
        return "RECOVERY"

    if elapsed < SUPPLY_INTERRUPTION_END:
        return "SUPPLY_INTERRUPTION"

    return "NORMAL_MONITORING"


def write_scenario_state(scenario, elapsed, intensity, supply_interruption):
    """Publish the current phase for the Streamlit dashboard.

    Never allowed to crash the monitoring loop.
    """

    state = {
        "scenario": scenario,
        "elapsed_s": round(elapsed, 1),
        "demo_end_s": DEMO_END,
        "contamination_intensity": round(float(intensity), 3),
        "supply_interruption": bool(supply_interruption),
        "network_online": scenario != "NETWORK_OUTAGE",
        "updated_at": time.time(),
        "timeline": TIMELINE,
    }

    try:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        temp_path = STATE_PATH.with_suffix(".tmp")
        temp_path.write_text(json.dumps(state), encoding="utf-8")
        os.replace(temp_path, STATE_PATH)

    except Exception as error:
        logger.warning("Could not write scenario state: %s", error)


# --------------------------------------------------
# RECOVERY HELPERS
# --------------------------------------------------

def drain_pending(database, sync_manager, max_attempts=5):
    """Keep syncing until nothing is pending, or give up after a few tries."""

    for attempt in range(1, max_attempts + 1):

        pending = database.get_pending_count()

        if pending == 0:
            return True

        logger.info(
            "FINAL REPLAY | attempt=%s | pending=%s",
            attempt,
            pending
        )

        sync_manager.sync_once()
        time.sleep(1)

    return database.get_pending_count() == 0


def log_recovery_result(database, pending_at_recovery):
    """Log whether the buffered backlog was fully delivered."""

    stats = database.get_statistics()
    still_pending = stats["pending_readings"]

    if still_pending == 0:
        logger.info(
            "RECOVERY RESULT | PASS | backlog_at_recovery=%s | "
            "pending=0 | synced=%s | total=%s",
            pending_at_recovery,
            stats["synced_readings"],
            stats["total_readings"]
        )
    else:
        logger.warning(
            "RECOVERY RESULT | INCOMPLETE | backlog_at_recovery=%s | "
            "pending=%s | synced=%s | total=%s",
            pending_at_recovery,
            still_pending,
            stats["synced_readings"],
            stats["total_readings"]
        )


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
    demo_completed = False

    supply_interruption_active = False
    pending_at_recovery = 0
    offline_nodes = set()

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

            # --------------------------------------
            # STOP AFTER THE DEMO DURATION
            # --------------------------------------

            if elapsed >= DEMO_END:

                logger.info(
                    "DEMO DURATION REACHED | elapsed=%.0fs",
                    elapsed
                )

                demo_completed = True
                break

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
            # SUPPLY INTERRUPTION WINDOW
            # --------------------------------------

            supply_interruption = (
                scenario == "SUPPLY_INTERRUPTION"
            )

            if supply_interruption != supply_interruption_active:

                if supply_interruption:
                    logger.warning(
                        "SCENARIO STARTED | SUPPLY INTERRUPTION"
                    )
                else:
                    logger.info(
                        "SUPPLY INTERRUPTION ENDED"
                    )

                supply_interruption_active = supply_interruption

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
                    "NETWORK RESTORED | reconnecting nodes"
                )

                # The outage disconnected every client, so they must be
                # reconnected before any buffered replay can succeed.
                for node_id, client in mqtt_clients.items():

                    if not client.connect():
                        offline_nodes.add(node_id)
                        logger.warning(
                            "RECONNECT FAILED | node=%s | will retry",
                            node_id
                        )

                pending_at_recovery = database.get_pending_count()

                logger.warning(
                    "BUFFERED TELEMETRY REPLAY STARTING | pending=%s",
                    pending_at_recovery
                )

                recovery_started = True

            elif (
                recovery_started
                and offline_nodes
                and scenario != "NETWORK_OUTAGE"
            ):

                for node_id in list(offline_nodes):

                    if mqtt_clients[node_id].connect():
                        offline_nodes.discard(node_id)
                        logger.info(
                            "RECONNECTED | node=%s",
                            node_id
                        )

            # --------------------------------------
            # CONTAMINATION INTENSITY
            # --------------------------------------
            # Once the event has started, keep following its curve through
            # the outage AND the recovery phase, so the contamination washes
            # out gradually instead of dropping to zero at 90 seconds.

            if contamination_started:

                event_intensity = contamination.get_intensity(
                    current_time
                )

            else:

                event_intensity = 0.0

            logger.info(
                "SCENARIO STATE | scenario=%s | elapsed=%.0fs | "
                "contamination=%.2f | supply_interruption=%s",
                scenario,
                elapsed,
                event_intensity,
                supply_interruption
            )

            write_scenario_state(
                scenario,
                elapsed,
                event_intensity,
                supply_interruption
            )

            # --------------------------------------
            # GENERATE AND STORE TELEMETRY
            # --------------------------------------

            for node_id, node in NODES.items():

                reading = generate_reading(
                    node=node,
                    event_intensity=event_intensity,
                    current_time=current_time,
                    supply_interruption=supply_interruption
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

                if scenario == "RECOVERY":

                    logger.info(
                        "REPLAY PROGRESS | pending=%s",
                        database.get_pending_count()
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

        # ------------------------------------------
        # END OF DEMO: FINISH REPLAY, THEN REPORT
        # ------------------------------------------

        if demo_completed:

            drain_pending(database, sync_manager)
            log_recovery_result(database, pending_at_recovery)

            write_scenario_state(
                "DEMO_COMPLETE",
                time.time() - start_time,
                0.0,
                False
            )

        else:

            write_scenario_state(
                "STOPPED",
                time.time() - start_time,
                0.0,
                False
            )

            logger.warning(
                "RUN INTERRUPTED BEFORE DEMO END | "
                "pending=%s readings remain buffered",
                database.get_pending_count()
            )

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