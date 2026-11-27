# WaterWatch viva guide

Use this as a study aid and explain the system in your own words. Be ready to
show the relevant code and live output rather than memorising these paragraphs.

## One-minute system overview

WaterWatch simulates three river monitoring nodes. Every five seconds the
simulator generates pH, turbidity, dissolved solids, temperature, flow, and
location. The same contamination intensity affects turbidity, TDS, pH, and
flow, so an intrusion changes several related measurements together. Each
reading is saved in SQLite before any network publish is attempted. The sync
manager sends unsent readings to ThingsBoard over MQTT with TLS and QoS 1.
The message carries the original Unix timestamp in milliseconds. If the
connection is unavailable, readings stay in SQLite and are replayed in time
order after connectivity returns. Streamlit reads the local database and
shows recent readings, alarms, charts, node locations, and scenario progress.

## How to explain each part

### Sensor simulation

`simulator/sensor_model.py` creates the five sensor values plus coordinates.
Random baseline values represent normal variation. A shared event intensity
raises turbidity and TDS, lowers pH with a nonlinear curve and floor, and
changes flow. A daily sine curve plus small noise represents water temperature.
When the supply interruption flag is active, flow is set to zero.

The model is a plausible demonstration model, not a calibrated hydrological
model. In particular, the TDS increase coefficient and the pH response need
field data before they could be treated as real-world predictions.

### Contamination timeline

`simulator/contamination.py` gives the event a fast rise and exponential
washout. `main.py` starts the event at the contamination phase and keeps
calculating its intensity during the network outage and recovery. That is why
the simulated water quality does not instantly return to baseline when the
scenario phase changes.

### Store-and-forward

`database/sqlite_manager.py` uses SQLite with WAL mode. It inserts a reading
before any publish attempt and marks it synced only after delivery is
confirmed. Pending records are ordered by acquisition time. If the pending
buffer reaches 100,000 rows, it removes the oldest pending row and records
that eviction in `buffer_events`, preserving newer observations.

### MQTT and replay

`communication/mqtt_client.py` connects to ThingsBoard on TLS port 8883,
authenticates with the per-device access token, and publishes with QoS 1. The
payload uses ThingsBoard's timestamped form: `{"ts": ..., "values": {...}}`.
`communication/sync_manager.py` reconnects with per-node exponential backoff
and replays the oldest pending records first. A row is marked synced only
after the MQTT publish is acknowledged.

### Dashboard

`streamlit_app.py` reads the local SQLite database and scenario state file. It
is a local monitoring interface; it does not configure the ThingsBoard cloud
dashboard or its server-side alarm rules.

## Important distinction for questions

The repository demonstrates the edge simulator, local persistence, MQTT
transport, and a local dashboard. The assignment also requires a configured
ThingsBoard device profile, at least three provisioned devices, dashboard
widgets, inactivity detection, and alarm rules with hysteresis. Those items
must be shown in the ThingsBoard instance or supported by configuration
exports/screenshots; code in this folder alone does not prove they are
configured.

The assignment additionally requires measured latency, delivery ratio, alarm
activation delay, buffer flush throughput, recovery time, and data loss. The
current application logs useful counts but does not calculate all of these
metrics. Report measurements only after collecting them from an actual run.

## Questions to practise

1. Why is a reading written to SQLite before MQTT publishing?
2. How does the system avoid assigning replayed readings the time they arrived
   at the cloud?
3. What happens when the pending buffer reaches its capacity, and why?
4. How are the sensor parameters coupled during a contamination event?
5. Why is pH bounded below, and why is temperature modelled with a daily cycle?
6. What is the difference between the local Streamlit view and the ThingsBoard
   dashboard required by the brief?
7. Which measurements still need to be collected for the technical manuscript?

## Demonstration order

1. Start `python main.py` and show baseline readings and the three nodes.
2. Show the local dashboard updating.
3. Let the scripted contamination phase run and point out turbidity, TDS, and
   pH changing together.
4. During the network outage, show the SQLite pending count rising while the
   simulator continues running.
5. During recovery, show rows replaying and the pending count falling.
6. Show the corresponding ThingsBoard dashboard, alarms, and historical
   backfill from your configured cloud instance.
