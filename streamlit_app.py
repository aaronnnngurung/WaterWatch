"""
WaterWatch - Local Visual Monitoring Dashboard
Run with: streamlit run streamlit_app.py
"""

import json
import sqlite3
import time
from pathlib import Path
from datetime import datetime

import pandas as pd
import streamlit as st


# --------------------------------------------------
# CONFIGURATION
# --------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "database" / "waterwatch.db"

# Written by main.py every sampling cycle.
STATE_PATH = BASE_DIR / "database" / "scenario_state.json"
STATE_STALE_SECONDS = 15

st.set_page_config(
    page_title="WaterWatch Monitoring",
    page_icon="💧",
    layout="wide",
    initial_sidebar_state="expanded"
)

NODE_NAMES = {
    "rasuwa": "WaterWatch_Rasuwa",
    "trishuli": "WaterWatch_Trishuli",
    "nuwakot": "WaterWatch_Nuwakot"
}

REFRESH_SECONDS = 5

# scenario key -> (icon, title, description, banner style)
SCENARIO_DISPLAY = {
    "BASELINE": (
        "🟢", "Baseline",
        "Normal water conditions.",
        "success"
    ),
    "CONTAMINATION": (
        "🔴", "Rainfall Contamination",
        "Rainfall is washing contaminants into the water source.",
        "error"
    ),
    "NETWORK_OUTAGE": (
        "🟠", "Network Outage",
        "Cloud link is down. Readings are being buffered locally.",
        "warning"
    ),
    "RECOVERY": (
        "🔵", "Network Recovery",
        "Cloud link restored. Buffered readings are being replayed.",
        "info"
    ),
    "SUPPLY_INTERRUPTION": (
        "🟣", "Supply Interruption",
        "Water flow has been interrupted.",
        "error"
    ),
    "NORMAL_MONITORING": (
        "🟢", "Normal Monitoring",
        "Conditions have returned to normal.",
        "success"
    ),
    "DEMO_COMPLETE": (
        "⚪", "Demonstration Complete",
        "The scenario has finished and the simulator has stopped.",
        "info"
    ),
    "STOPPED": (
        "⚪", "Simulator Stopped",
        "The simulator was stopped before the scenario finished.",
        "warning"
    ),
}

FINAL_STATES = ("DEMO_COMPLETE", "STOPPED")


# --------------------------------------------------
# DATABASE
# --------------------------------------------------

def get_connection():
    if not DB_PATH.exists():
        return None

    connection = sqlite3.connect(
        str(DB_PATH),
        timeout=10
    )
    connection.row_factory = sqlite3.Row
    return connection


def load_telemetry():
    connection = get_connection()

    if connection is None:
        return pd.DataFrame()

    try:
        rows = connection.execute("""
            SELECT id, node_id, timestamp_ms,
                   payload_json, synced
            FROM telemetry
            ORDER BY timestamp_ms DESC
            LIMIT 3000
        """).fetchall()

        records = []

        for row in rows:
            try:
                payload = json.loads(row["payload_json"])

                records.append({
                    "id": row["id"],
                    "node_id": row["node_id"],
                    "timestamp_ms": row["timestamp_ms"],
                    "timestamp": datetime.fromtimestamp(
                        row["timestamp_ms"] / 1000
                    ),
                    "ph": payload.get("ph"),
                    "turbidity_ntu": payload.get("turbidity_ntu"),
                    "tds_ppm": payload.get("tds_ppm"),
                    "water_temp_c": payload.get("water_temp_c"),
                    "flow_lpm": payload.get("flow_lpm"),
                    "latitude": payload.get("latitude"),
                    "longitude": payload.get("longitude"),
                    "synced": row["synced"]
                })

            except (ValueError, TypeError, json.JSONDecodeError):
                continue

        return pd.DataFrame(records)

    finally:
        connection.close()


def load_buffer_events():
    connection = get_connection()

    if connection is None:
        return pd.DataFrame()

    try:
        rows = connection.execute("""
            SELECT *
            FROM buffer_events
            ORDER BY id DESC
            LIMIT 100
        """).fetchall()

        return pd.DataFrame([dict(row) for row in rows])

    finally:
        connection.close()


# --------------------------------------------------
# SCENARIO STATUS
# --------------------------------------------------

def load_scenario_state():
    """Read the status file written by main.py. Returns None if unavailable."""

    if not STATE_PATH.exists():
        return None

    try:
        return json.loads(
            STATE_PATH.read_text(encoding="utf-8")
        )

    except (OSError, ValueError):
        # File may be mid-write or unreadable; try again next refresh.
        return None


def render_scenario_status():

    st.subheader("🎬 Demonstration Scenario")

    state = load_scenario_state()

    if state is None:
        st.info(
            "No scenario information yet. "
            "Start the WaterWatch Python application."
        )
        return

    scenario = state.get("scenario", "UNKNOWN")
    elapsed = float(state.get("elapsed_s", 0))
    demo_end = float(state.get("demo_end_s", 0))
    intensity = float(state.get("contamination_intensity", 0))
    network_online = bool(state.get("network_online", True))
    age = time.time() - float(state.get("updated_at", 0))

    icon, title, description, style = SCENARIO_DISPLAY.get(
        scenario,
        ("⚪", scenario, "", "info")
    )

    is_stale = scenario not in FINAL_STATES and age > STATE_STALE_SECONDS

    if is_stale:

        st.warning(
            f"⚠️ The simulator does not appear to be running "
            f"(last update {age:.0f} seconds ago). "
            f"Last known phase: **{title}**."
        )

    else:

        banner = {
            "success": st.success,
            "error": st.error,
            "warning": st.warning,
            "info": st.info,
        }[style]

        banner(f"{icon} **{title}** | {description}")

    m1, m2, m3 = st.columns(3)

    m1.metric(
        "Elapsed Time",
        f"{elapsed:.0f} s / {demo_end:.0f} s"
    )

    m2.metric(
        "Cloud Link",
        "Online" if network_online else "Offline (buffering)"
    )

    m3.metric(
        "Contamination Level",
        f"{intensity * 100:.0f} %"
    )

    if demo_end > 0:
        st.progress(min(elapsed / demo_end, 1.0))

    timeline = state.get("timeline", [])

    if timeline:

        parts = []

        for name, start, end in timeline:

            phase_title = SCENARIO_DISPLAY.get(
                name,
                ("", name, "", "")
            )[1]

            label = f"{phase_title} ({start}–{end} s)"

            if name == scenario:
                label = f"**▶ {label}**"

            parts.append(label)

        st.caption(" → ".join(parts))


# --------------------------------------------------
# ALARM DETECTION
# --------------------------------------------------

def check_alarms(row):

    alarms = []

    ph = row.get("ph")
    turbidity = row.get("turbidity_ntu")
    tds = row.get("tds_ppm")
    flow = row.get("flow_lpm")

    node = NODE_NAMES.get(
        row.get("node_id"),
        row.get("node_id")
    )

    if pd.notna(ph):
        if ph < 6.5:
            alarms.append({
                "Node": node,
                "Alarm": "Low pH",
                "Severity": "CRITICAL",
                "Reading": f"{ph:.2f}",
                "Condition": "pH below 6.5"
            })

        elif ph > 8.5:
            alarms.append({
                "Node": node,
                "Alarm": "High pH",
                "Severity": "CRITICAL",
                "Reading": f"{ph:.2f}",
                "Condition": "pH above 8.5"
            })

    if pd.notna(turbidity):
        if turbidity > 200:
            alarms.append({
                "Node": node,
                "Alarm": "Gross Contamination",
                "Severity": "CRITICAL",
                "Reading": f"{turbidity:.1f} NTU",
                "Condition": "Turbidity above 200 NTU"
            })

        elif turbidity > 50:
            alarms.append({
                "Node": node,
                "Alarm": "High Turbidity",
                "Severity": "WARNING",
                "Reading": f"{turbidity:.1f} NTU",
                "Condition": "Turbidity above 50 NTU"
            })

    if pd.notna(tds) and tds > 500:
        alarms.append({
            "Node": node,
            "Alarm": "High TDS",
            "Severity": "CRITICAL",
            "Reading": f"{tds:.0f} ppm",
            "Condition": "TDS above 500 ppm"
        })

    if pd.notna(flow) and flow == 0:
        alarms.append({
            "Node": node,
            "Alarm": "Supply Interruption",
            "Severity": "MAJOR",
            "Reading": "0 L/min",
            "Condition": "No water flow detected"
        })

    return alarms


# --------------------------------------------------
# HEADER
# --------------------------------------------------

st.title("💧 WaterWatch Monitoring System")

st.caption(
    "Local water-quality monitoring and visual alert dashboard"
)

st.divider()


# --------------------------------------------------
# SIDEBAR
# --------------------------------------------------

st.sidebar.title("Monitoring Controls")

auto_refresh = st.sidebar.checkbox(
    "Enable automatic refresh",
    value=True
)

selected_node = st.sidebar.selectbox(
    "Select Monitoring Node",
    ["All Nodes"] + list(NODE_NAMES.values())
)

st.sidebar.caption(
    f"Refresh interval: {REFRESH_SECONDS} seconds"
)

if st.sidebar.button("Refresh Now", use_container_width=True):
    st.rerun()


# --------------------------------------------------
# SCENARIO STATUS BANNER
# --------------------------------------------------

render_scenario_status()

st.divider()


# --------------------------------------------------
# LOAD DATA
# --------------------------------------------------

df = load_telemetry()

if df.empty:

    st.warning(
        "No telemetry records found. "
        "Start the WaterWatch Python application first."
    )

    st.info(
        f"Expected database location: {DB_PATH}"
    )

    st.stop()


# --------------------------------------------------
# FILTER DATA
# --------------------------------------------------

if selected_node != "All Nodes":

    selected_id = {
        value: key for key, value in NODE_NAMES.items()
    }[selected_node]

    df = df[df["node_id"] == selected_id]


if df.empty:
    st.warning("No readings available for this node.")
    st.stop()


latest = (
    df.sort_values("timestamp")
    .groupby("node_id")
    .tail(1)
    .sort_values("node_id")
)

latest_reading = latest.iloc[-1]


# --------------------------------------------------
# SYSTEM OVERVIEW
# --------------------------------------------------

total_records = len(df)

synced_records = int(
    (df["synced"] == 1).sum()
)

pending_records = int(
    (df["synced"] == 0).sum()
)

col1, col2, col3, col4 = st.columns(4)

col1.metric(
    "Monitoring Nodes",
    latest["node_id"].nunique()
)

col2.metric(
    "Stored Readings",
    total_records
)

col3.metric(
    "Synchronised",
    synced_records
)

col4.metric(
    "Pending Upload",
    pending_records
)


# --------------------------------------------------
# CURRENT WATER QUALITY
# --------------------------------------------------

st.subheader("Current Water Quality")

selected_latest = latest.iloc[-1]

ph = selected_latest["ph"]
turbidity = selected_latest["turbidity_ntu"]
tds = selected_latest["tds_ppm"]
temperature = selected_latest["water_temp_c"]
flow = selected_latest["flow_lpm"]

c1, c2, c3, c4, c5 = st.columns(5)

c1.metric(
    "pH Level",
    f"{ph:.2f}" if pd.notna(ph) else "N/A"
)

c2.metric(
    "Turbidity",
    f"{turbidity:.1f} NTU" if pd.notna(turbidity) else "N/A"
)

c3.metric(
    "TDS",
    f"{tds:.0f} ppm" if pd.notna(tds) else "N/A"
)

c4.metric(
    "Temperature",
    f"{temperature:.1f} °C" if pd.notna(temperature) else "N/A"
)

c5.metric(
    "Water Flow",
    f"{flow:.1f} L/min" if pd.notna(flow) else "N/A"
)


# --------------------------------------------------
# VISUAL ALARMS
# --------------------------------------------------

st.divider()
st.subheader("🚨 Water Quality Alarm Centre")

all_alarms = []

for _, row in latest.iterrows():
    all_alarms.extend(check_alarms(row))

critical_count = sum(
    a["Severity"] == "CRITICAL" for a in all_alarms
)

warning_count = sum(
    a["Severity"] == "WARNING" for a in all_alarms
)

major_count = sum(
    a["Severity"] == "MAJOR" for a in all_alarms
)

a1, a2, a3 = st.columns(3)

a1.metric("Critical Alarms", critical_count)
a2.metric("Warnings", warning_count)
a3.metric("Major Alarms", major_count)


if not all_alarms:

    st.success(
        "All monitored parameters are currently within "
        "their configured alarm thresholds."
    )

else:

    for alarm in all_alarms:

        message = (
            f"**{alarm['Alarm']}** | "
            f"{alarm['Node']} | "
            f"{alarm['Reading']} | "
            f"{alarm['Condition']}"
        )

        if alarm["Severity"] == "CRITICAL":
            st.error("🔴 " + message)

        elif alarm["Severity"] == "WARNING":
            st.warning("🟡 " + message)

        else:
            st.info("🔵 " + message)


# --------------------------------------------------
# NODE COMPARISON
# --------------------------------------------------

st.divider()
st.subheader("📡 Monitoring Node Status")

display_columns = [
    "node_id",
    "timestamp",
    "ph",
    "turbidity_ntu",
    "tds_ppm",
    "water_temp_c",
    "flow_lpm",
    "synced"
]

node_table = latest[display_columns].copy()

node_table["node_id"] = node_table["node_id"].map(
    NODE_NAMES
).fillna(node_table["node_id"])

node_table["synced"] = node_table["synced"].map({
    1: "Synchronised",
    0: "Pending"
})

st.dataframe(
    node_table,
    use_container_width=True,
    hide_index=True
)


# --------------------------------------------------
# HISTORICAL CHARTS
# --------------------------------------------------

st.divider()
st.subheader("📈 Historical Water Quality Trends")

chart_data = df.sort_values("timestamp").copy()

tab1, tab2, tab3, tab4 = st.tabs([
    "pH",
    "Turbidity",
    "TDS",
    "Temperature & Flow"
])

with tab1:

    st.caption("Normal operating reference: pH 6.8–7.6")

    st.line_chart(
        chart_data,
        x="timestamp",
        y="ph",
        color="node_id",
        height=300
    )

    st.caption(
        "Critical alarm thresholds: below 6.5 or above 8.5."
    )


with tab2:

    st.caption(
        "Warning above 50 NTU | Critical above 200 NTU"
    )

    st.line_chart(
        chart_data,
        x="timestamp",
        y="turbidity_ntu",
        color="node_id",
        height=300
    )


with tab3:

    st.caption("Critical alarm threshold: above 500 ppm")

    st.line_chart(
        chart_data,
        x="timestamp",
        y="tds_ppm",
        color="node_id",
        height=300
    )


with tab4:

    st.line_chart(
        chart_data,
        x="timestamp",
        y=["water_temp_c", "flow_lpm"],
        color="node_id",
        height=300
    )


# --------------------------------------------------
# LOCATION MAP
# --------------------------------------------------

st.divider()
st.subheader("🗺️ Monitoring Node Locations")

map_data = latest.dropna(
    subset=["latitude", "longitude"]
)[["latitude", "longitude"]].copy()

map_data = map_data.rename(columns={
    "latitude": "lat",
    "longitude": "lon"
})

if not map_data.empty:
    st.map(map_data, zoom=7)
else:
    st.info("No node location information available.")


# --------------------------------------------------
# BUFFER EVENT LOG
# --------------------------------------------------

st.divider()
st.subheader("📦 Store-and-Forward Event Log")

events = load_buffer_events()

if events.empty:

    st.info("No buffer events recorded.")

else:

    st.dataframe(
        events,
        use_container_width=True,
        hide_index=True
    )


# --------------------------------------------------
# RAW TELEMETRY
# --------------------------------------------------

with st.expander("View Raw Telemetry Records"):

    st.dataframe(
        df.sort_values(
            "timestamp",
            ascending=False
        ),
        use_container_width=True,
        hide_index=True
    )


# --------------------------------------------------
# FOOTER AND AUTO REFRESH
# --------------------------------------------------

st.divider()

st.caption(
    f"Last dashboard refresh: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
)

st.caption(
    "WaterWatch | Local monitoring interface | "
    "ThingsBoard remains the official cloud monitoring platform."
)

if auto_refresh:
    time.sleep(REFRESH_SECONDS)
    st.rerun()