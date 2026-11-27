"""Generate simulated water-quality telemetry for a WaterWatch node."""

import math
import random
import time
from datetime import datetime


PH_FLOOR = 5.5


def generate_reading(
    node,
    event_intensity=0.0,
    supply_interruption=False,
    current_time=None
):
    """
    Generate one sensor reading.

    node must contain:
        name, latitude, longitude

    event_intensity:
        0.0 = normal conditions
        1.0 = peak contamination
    """

    now = time.time() if current_time is None else current_time
    intensity = max(0.0, min(1.0, event_intensity))

    # Draw a fresh baseline value for each sensor reading. During an event,
    # the same intensity then shifts several parameters together, so the
    # readings reflect one shared physical disturbance rather than unrelated
    # random spikes.
    base_ph = random.uniform(6.8, 7.6)
    base_turbidity = random.uniform(2.0, 8.0)
    base_tds = random.uniform(120.0, 250.0)
    base_flow = random.uniform(8.0, 18.0)

    # Turbidity rises sharply during silt/sewage intrusion. The peak range
    # follows the assignment's 100–800 NTU event range.
    turbidity_peak = random.uniform(100.0, 800.0)
    turbidity = base_turbidity + (
        turbidity_peak - base_turbidity
    ) * intensity

    # Dissolved material increases with contamination.
    # The coefficient is a simulation assumption, not a measured
    # physical constant. It can be calibrated in later experiments.
    tds_increase = random.uniform(180.0, 450.0)
    tds = base_tds + (tds_increase * intensity)

    # Nonlinear pH depression, limited by the configured floor.
    ph_drop = 1.8 * (intensity ** 1.5)
    ph = max(PH_FLOOR, base_ph - ph_drop)

    # Water temperature follows a 24-hour daily cycle.
    local_hour = datetime.fromtimestamp(now).hour
    daily_cycle = math.sin(
        (2.0 * math.pi * (local_hour - 6)) / 24.0
    )
    water_temp = (
        20.0
        + 3.0 * daily_cycle
        + random.uniform(-0.5, 0.5)
    )

    # Flow changes during intrusion due to a pressure transient.
    flow = base_flow - (base_flow * 0.30 * intensity)
    flow += random.uniform(-0.4, 0.4)

    if supply_interruption:
        flow = 0.0

    # Keep values within reasonable simulation bounds.
    turbidity = max(0.0, turbidity)
    tds = max(0.0, tds)
    flow = max(0.0, flow)

    return {
        "ts": int(now * 1000),
        "ph": round(ph, 2),
        "turbidity_ntu": round(turbidity, 1),
        "tds_ppm": round(tds),
        "water_temp_c": round(water_temp, 1),
        "flow_lpm": round(flow, 1),
        "latitude": float(node["latitude"]),
        "longitude": float(node["longitude"]),
    }
