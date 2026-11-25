
"""Configuration for the three WaterWatch virtual monitoring nodes."""

import os
from dotenv import load_dotenv

load_dotenv()

NODES = {
    "rasuwa": {
        "name": "WaterWatch_Rasuwa",
        "location": "Dhunche, Rasuwa",
        "latitude": 28.1053,
        "longitude": 85.3076915,
        "token": os.getenv("RASUWA_TOKEN"),
    },

    "trishuli": {
        "name": "WaterWatch_Trishuli",
        "location": "Trishuli Bazaar, Nuwakot",
        "latitude": 27.92225,
        "longitude": 85.14703,
        "token": os.getenv("TRISHULI_TOKEN"),
    },

    "nuwakot": {
        "name": "WaterWatch_Nuwakot",
        "location": "Bidur, Nuwakot",
        "latitude": 27.89,
        "longitude": 85.16,
        "token": os.getenv("NUWAKOT_TOKEN"),
    },
}


def validate_nodes():
    """Check node configuration before starting the simulator."""

    for node_id, node in NODES.items():
        if not node["token"] or node["token"].startswith("PASTE_"):
            raise ValueError(
                f"Missing ThingsBoard access token for {node_id}"
            )

        if not -90 <= node["latitude"] <= 90:
            raise ValueError(f"Invalid latitude for {node_id}")

        if not -180 <= node["longitude"] <= 180:
            raise ValueError(f"Invalid longitude for {node_id}")

    print("All three WaterWatch nodes are configured successfully.")


if __name__ == "__main__":
    validate_nodes()

    for node_id, node in NODES.items():
        print(
            f"{node_id}: {node['name']} | "
            f"{node['latitude']}, {node['longitude']}"
        )
