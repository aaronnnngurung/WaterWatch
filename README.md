# WaterWatch

WaterWatch is a Python-based virtual edge system for monitoring river water
quality at three locations in Nepal. It simulates pH, turbidity, total dissolved
solids (TDS), water temperature, and flow; stores telemetry locally in SQLite;
and sends timestamped readings to ThingsBoard over MQTT with TLS.

## What is implemented

- Three configurable virtual monitoring nodes with latitude and longitude.
- A scripted 130-second demonstration covering baseline conditions,
  contamination, network outage, recovery, supply interruption, and normal
  monitoring.
- Coupled contamination effects on turbidity, TDS, pH, and flow.
- SQLite WAL storage before network publishing, with a 100,000-row pending
  buffer and oldest-first eviction logging.
- Timestamp-preserving MQTT publish and chronological store-and-forward replay.
- A local Streamlit dashboard for telemetry, scenario status, alarms, trends,
  and node locations.

The Python simulator, SQLite buffer, MQTT transport, and local dashboard are
implemented here. ThingsBoard device provisioning, cloud dashboard widgets,
alarm rules, and performance measurements must be configured or collected for
the assessment and are not supplied by this code alone.

## Requirements

- Python 3.10 or newer
- A ThingsBoard instance and three device access tokens
- Network access to the MQTT TLS endpoint on port 8883

Install the Python packages:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Copy `.env.example` to `.env` and fill in the host and device tokens. Keep the
real `.env` file private; it is excluded from Git.

## Run

Start the simulator:

```powershell
python main.py
```

In a second terminal, start the local dashboard:

```powershell
streamlit run streamlit_app.py
```

The scripted demonstration ends after 130 seconds. SQLite data is stored in
`database/waterwatch.db`, and logs are written to `logs/waterwatch.log`.

## Submission and viva notes

See [VIVA_GUIDE.md](VIVA_GUIDE.md) for an explanation of the data path, a
demonstration sequence, and questions to practise. Add ThingsBoard screenshots
or exports, a complete demonstration log, and measured performance results to
the implementation submission as required by the assignment.
