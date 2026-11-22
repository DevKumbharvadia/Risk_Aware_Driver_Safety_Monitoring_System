# Fleet Guardian – Risk-Aware Driver Safety Monitoring System

Fleet Guardian is a risk-aware driver safety monitoring system designed to monitor driver behaviour and vehicle telemetry through a centralized fleet manager.

The system uses a **manager PC** to run the owner dashboard, local fleet server, risk engine, and SQLite database. Each vehicle is assigned an individual phone link. The driver opens this link in a smartphone browser, allowing the phone to provide camera-based behaviour predictions and GPS telemetry.

Camera inference runs directly in the driver's smartphone browser using **MobileNetV3 Small ONNX**. The manager PC receives the predictions and telemetry, validates incoming data, evaluates driving risk, and stores monitoring results.

Each connected phone has its own access token, session ID, risk engine, and camera preview. This keeps vehicle monitoring sessions isolated.

## System Architecture

The system follows a phone-to-manager architecture:

1. **Driver smartphone**
   - Opens the vehicle-specific monitoring link in a browser.
   - Captures camera frames.
   - Runs MobileNetV3 Small ONNX inference locally.
   - Collects GPS speed and location information.
   - Sends behaviour predictions and telemetry to the manager PC.

2. **Manager PC**
   - Hosts the local phone communication service.
   - Receives and validates incoming predictions and telemetry.
   - Maintains separate sessions for connected vehicles.
   - Runs the explainable risk engine.
   - Stores monitoring samples and events in SQLite.
   - Displays live monitoring information through the owner dashboard.

3. **Owner dashboard**
   - Displays fleet and vehicle information.
   - Shows active monitoring sessions.
   - Displays individual vehicle camera previews and risk information.
   - Provides event history and monitoring logs.

## Quick Start

### Requirements

- Windows PC
- Python and pip
- Google Chrome on the driver's smartphone
- Smartphone with a working camera and GPS
- Internet connection for Cloudflare Quick Tunnel mode

### Installation

The recommended way to launch the application is:

```powershell
run.bat
```

The batch file creates the virtual environment and installs the dependencies from `requirements.txt` on the first run, then starts the manager application.

Alternatively, create and activate the virtual environment manually:

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Start the application:

```powershell
python main.py
```

### Run with Cloudflare Quick Tunnel

To make the phone monitoring service accessible over mobile data, launch:

```powershell
python main.py --trip
```

This starts a temporary Cloudflare Quick Tunnel and provides a public HTTPS URL for connecting driver smartphones.

The PC-side helper executable is located at:

```text
tools/cloudflared.exe
```

If it is not available, install Cloudflare Tunnel using:

```powershell
winget install --id Cloudflare.cloudflared -e
```

Closing the owner dashboard stops the manager application and its associated services.

## Connecting Driver Smartphones

### LAN Mode

1. Start the manager using `run.bat` or `python main.py`.
2. Open the **Connect a driver phone** window.
3. Select the required vehicle.
4. Copy its individual phone link.
5. Open the link in Chrome on the driver's smartphone.
6. Grant the requested camera and location permissions.
7. Start monitoring.

The smartphone browser performs camera inference and sends predictions and telemetry to the manager PC.

LAN mode uses locally generated HTTPS certificates. Follow the certificate installation instructions provided by the application when connecting through HTTPS on the local network.

### Trip Mode – Mobile Data

1. Start the manager using:

   ```powershell
   python main.py --trip
   ```

2. Wait for Cloudflare Quick Tunnel to establish a connection.
3. Copy the vehicle-specific phone link.
4. Share the link with the corresponding driver.
5. Open it in Chrome using mobile data or another internet connection.
6. Grant camera and location permissions.
7. Start monitoring.

No manual local certificate installation is required for the public HTTPS tunnel.

Each vehicle receives its own access token and monitoring session. New links are generated when the manager starts again.

## Owner Dashboard

The owner interface is built using **Tkinter**.

| Section | Functionality |
|---|---|
| Overview | Fleet status, vehicle information, online status, risk levels and recent activity |
| Vehicles | Vehicle management and monitoring access |
| Drivers | Driver information and vehicle associations |
| Routes | Route management |
| Assignments | Vehicle-driver assignments and trip management |
| Live Monitoring | Individual vehicle monitoring, camera preview, risk score and telemetry |
| Logs & Reports | Monitoring history, risk events, filtering and CSV export |

The owner dashboard communicates with the fleet server rather than accessing SQLite directly.

## Camera-Based Driver Behaviour Monitoring

Camera processing takes place inside the driver's smartphone browser.

The system uses **MobileNetV3 Small ONNX** for browser-side behaviour classification.

The browser sends the resulting predictions to the manager PC instead of transmitting camera inference workloads for server-side classification.

The manager PC processes the received predictions through the risk engine and associates them with the corresponding vehicle and monitoring session.

Camera previews are maintained separately for individual vehicle sessions.

Predictions are validated before being used for risk assessment. Missing, invalid, or stale predictions must not be treated as confirmed driver behaviour.

## GPS Speed and Telemetry

The driver's smartphone provides GPS-based speed information.

The manager PC validates incoming telemetry before using it in the risk engine.

The phone communication layer applies validation limits, including:

- Maximum accepted speed: 250 km/h.
- Maximum GPS reading age: 5 seconds.
- Maximum accepted future timestamp: 2 seconds.
- Maximum GPS accuracy threshold: 30 metres.

Invalid, stale, or excessively inaccurate GPS readings are rejected.

Speed information is used as contextual input for risk assessment and speed-aware attention monitoring.

GPS speed is not a replacement for calibrated vehicle instrumentation.

## Explainable Risk Assessment

The manager PC runs the explainable risk engine.

Instead of relying exclusively on a machine-learning classification score, the risk engine evaluates incoming behaviour predictions and telemetry using temporal rules.

The engine maintains separate monitoring state for individual vehicle sessions.

Risk assessment considers:

- Driver behaviour predictions.
- Duration of detected behaviour.
- GPS speed context.
- Changes in monitoring conditions.
- Validity and freshness of incoming information.

Risk results include a score, risk level, and explanatory information describing the contributing evidence.

The system is a prototype monitoring solution. Its risk thresholds require further calibration and validation using real driving data.

## Session Isolation

Each connected vehicle has an independent monitoring session.

Session management includes:

- Individual vehicle access tokens.
- Unique session IDs.
- Separate risk-engine state.
- Individual camera previews.
- Independent telemetry and prediction handling.

This prevents predictions, camera previews, and risk information from being unintentionally shared between vehicles.

The manager validates the incoming session information before associating data with a vehicle.

## Local Fleet Server and Database

The fleet server provides communication between the driver smartphones and the manager application.

The architecture separates server communication and database operations from the owner interface.

SQLite is used for persistent fleet and monitoring data.

The main database is:

```text
data/fleet.sqlite3
```

Application configuration is maintained in the project's configuration files.

The database stores fleet information and monitoring records so that historical information can be accessed through the owner dashboard.

## Project Structure

The project separates application configuration, data, fleet communication, risk assessment, and supporting utilities.

Important project components include:

| Component | Responsibility |
|---|---|
| `main.py` | Application entry point |
| `config/` | Application configuration |
| `data/` | Database and runtime data |
| `fleet/` | Fleet management, phone communication and server functionality |
| `fleet/risk/` | Explainable risk assessment and attention rules |
| `tools/` | Supporting utilities, including Cloudflare Tunnel executable |
| `models/` | Machine-learning model assets |
| `requirements.txt` | Python dependencies |
| `run.bat` | Windows startup script |

The phone-side ONNX model and its browser assets are used by the smartphone monitoring interface.

## Security and Limitations

Fleet Guardian is a desktop research and development prototype.

Important considerations:

- Each vehicle uses an individual phone access token.
- Monitoring sessions use separate session identifiers.
- The phone communication service listens on localhost.
- Cloudflare Quick Tunnel provides temporary public HTTPS access in trip mode.
- Incoming telemetry and predictions are validated.
- Camera inference is performed on the smartphone rather than the manager PC.

The application is not yet intended for unrestricted production or public fleet deployment.

Additional authentication hardening, deployment security, real-world model validation, and operational testing are required before production use.

## Current Development Scope

The current implementation focuses on:

- Smartphone-based camera monitoring.
- MobileNetV3 Small ONNX browser inference.
- GPS-based speed extraction.
- Individual vehicle monitoring sessions.
- Explainable temporal risk assessment.
- Speed-aware attention monitoring.
- Centralized fleet management.
- SQLite-based monitoring records.
- LAN and Cloudflare Quick Tunnel connectivity.

Future improvements may include GPS route visualization, calibrated vehicle motion sensing, improved driver behaviour models, and validation using real-world driving footage.

## Disclaimer

Fleet Guardian is an experimental driver-monitoring and risk-assessment system.

Its predictions and risk scores are not guaranteed to identify every unsafe driving behaviour. It must not be treated as a certified safety system or as a substitute for responsible driving.