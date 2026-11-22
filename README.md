# Fleet Guardian

A risk-aware driver safety monitoring system for a fleet. One **manager PC** runs the owner dashboard and an HTTPS phone sensor terminal. Each vehicle is assigned a private phone link; the driver opens it in Chrome and the phone streams camera, GPS and motion to the manager PC, which runs the trained behavior classifier, the explainable risk rules, and SQLite storage. The owner sees live risk, camera, events and logs.

The application is launched from `main.py`. Run `run.bat` (it creates the virtual environment and installs `requirements.txt` on first run, then starts the manager) or, from the project folder:

```powershell
.\.venv\Scripts\python.exe main.py
```

That starts the manager over the trusted LAN. Add `--trip` to expose the phone service over a temporary Cloudflare Quick Tunnel instead, so a phone on mobile data can reach the manager PC without a LAN or certificate setup:

```powershell
.\.venv\Scripts\python.exe main.py --trip
```

Closing the owner window stops the manager. Each vehicle link contains its own access token; the next launch issues fresh links. Live inference and alerts depend on the phone staying connected. The PC helper for trip mode is `tools/cloudflared.exe`; on another PC without the bundled file, install it with `winget install --id Cloudflare.cloudflared -e`.

The owner interface uses **Tkinter**. The application, HTTP server, database, risk rules and phone terminal use the **Python standard library**; OpenCV, Pillow, MediaPipe, cryptography and CPU PyTorch are the installed dependencies. Camera behavior predictions run locally on the manager PC CPU; no GPU or model download is needed at startup.

## Quick start

On a fresh PC, double-click `run.bat` (it creates `.venv` and installs `requirements.txt` on first run, then starts the manager). The manager opens:

- The owner dashboard with three seeded vehicles, drivers, routes and active trips.
- A **Connect a driver phone** window listing each vehicle with a **Copy phone link** button.

The manager uses `data/fleet.sqlite3`. Closing the owner window stops the manager and phone terminal.

### Connect a phone (LAN)

1. On first use the manager generates local HTTPS certificates in `data/phone-link-<MANAGER_IP>/`. Copy `phone-ca.crt` to each phone and install it as a trusted CA certificate (Android: Settings → Security → Encryption → Install from storage; iOS: also enable full trust in Certificate Trust Settings).
2. Copy a vehicle's phone link and open it in Chrome on that vehicle's phone. Tap **Start monitoring** and allow camera and location access.
3. The phone streams JPEG frames plus GPS and motion; the manager classifies behavior, runs the risk rules, stores the sample and shows the live risk and camera preview in the owner's **Live monitoring** page.
4. Use **Refresh vehicle list** to add newly created vehicles.

Certificates expire after about 90 days. If the manager PC's LAN IP changes, delete the old `phone-link-*` folder so a fresh certificate set is generated.

### Connect a phone (trip / mobile data)

Run `main.py --trip`. No certificate install is needed; the manager prints a Cloudflare URL. Send each vehicle's link (built from that URL) to its driver and open it in Chrome over mobile data.

## Owner workflow

| Page | Features |
| --- | --- |
| Overview | Vehicle and active-trip counts, online count, HIGH/CAUTION/UNKNOWN counts, live fleet rows, recent transitions |
| Vehicles | Add/edit registration and model; open monitoring |
| Drivers | Add/edit name, license, contact; current vehicle and risk; open active vehicle |
| Routes | Add/edit route name, origin and destination |
| Assignments | Start/change assignments, end a trip, inspect trip history |
| Live monitoring | Selected vehicle's driver, route, score, reason, measurements, last sample time, camera |
| Logs & reports | Vehicle/driver/severity/date filters, latest 1,000 matching transitions, CSV export |

A driver cannot have two active trips. Reassigning a vehicle atomically closes the previous trip and creates a new one. Trip records retain the driver, vehicle and route names from assignment time, so later edits do not rewrite history. End a driver's existing trip before assigning that driver to another vehicle. No permanent deletion UI is provided because records support historical logs.

## Explainable risk rules

| Evidence while moving | Score contribution |
| --- | --- |
| Eyes closed for at least 2 seconds | 75 |
| Looking away / model turning | Speed-dependent: 45 at caution duration, 75 at high duration |
| Phone use for at least 2 seconds | 65; becomes 80 after 5 seconds |
| Yawning for at least 2 seconds | 25 |
| At least 3 yawning episodes in the last 60 seconds | 35 |
| Acceleration at or below −4 m/s² | 35 |

Scores sum and cap at 100. LOW is 0–29, CAUTION is 30–69, HIGH is 70–100. A lower level needs three seconds of recovery. Missing face produces UNKNOWN. Speed below 3 km/h suppresses motion-related warnings. The numerical bands are implementation choices to calibrate later, not validated road-safety thresholds.

### Speed-aware attention warnings

`fleet/risk/attention.py` contains the prototype settings for looking away and model-predicted turning:

| Speed context | Caution | High risk |
| --- | --- | --- |
| Stopped, below 3 km/h | Existing motion-alert suppression | Suppressed |
| Possible manoeuvring, 3–10 km/h inclusive | Attention warnings suppressed even during prolonged looking around | Suppressed |
| Moderate speed, above 10 through 30 km/h | After 5 seconds | After 10 seconds |
| Faster travel, above 30 km/h | After 3 seconds | After 6 seconds |

At startup the current speed chooses the band. Subsequent changes use a 2 km/h hysteresis margin and require two seconds of consistent observations: leaving manoeuvring requires above 12 km/h, entering it requires at most 8 km/h, entering faster travel requires above 32 km/h, and returning to moderate speed requires at most 28 km/h. Independently of that retained band, an actual reading at or below 10 km/h suppresses attention scoring immediately. Existing warnings still use the normal three-second recovery period.

On a confirmed band change, attention duration restarts from zero. Time spent looking around while manoeuvring never carries into a faster-speed alert. Phone use, eye closure, yawning and harsh-deceleration rules are not relaxed by the manoeuvring allowance; the below-3 km/h suppression still applies to them. Speed inputs come from the phone GPS; all thresholds need calibration with real data. Model weights do not change for this feature.

## Trained model

The exported MobileNetV3 Small classifier is installed at `models/driver_behavior/driver_behavior.pth` (metadata and Colab test report are beside it). It runs on the manager PC CPU. The classifier uses the whole frame; it does not provide bounding boxes, face-presence checks, eye closure or yawning measurements. Its risk mapping is:

| Model output | Application behavior |
| --- | --- |
| Talking/texting phone, score at least 0.65 | Phone-duration rules: caution after 2 seconds, high after 5 |
| Turning, score at least 0.65 | Speed-dependent attention rules above; low-speed manoeuvring allowance |
| Safe driving, score at least 0.65 | No modeled behavior flag; this does not certify driver safety |
| Other activities | UNKNOWN because this label mixes unrelated behaviors |
| Score below 0.65, missing model/camera, or stale frame | UNKNOWN; no fallback to invented readings |

The score is not a calibrated probability of correctness; the 0.65 cutoff needs calibration on separate validation footage. Predictions expire after 2.5 seconds without a fresh frame. Phone-use predictions also require a visible handset in the same frame (TorchVision SSDLite320); without one the result is `unconfirmed_activity` (UNKNOWN) rather than a phone warning. The browser-phone manager also runs Google's Face Landmarker on the manager PC for eye-blink and head-direction cues that feed the eye-closure and looking-aside rules.

The supplied Colab report records **91.25% test accuracy** and **0.9094 macro-F1** on 1,097 test images, using a provisional image-level split with no established driver/session independence. These are supplied dataset results, not live webcam performance. See [docs/MODEL_INTEGRATION.md](docs/MODEL_INTEGRATION.md) for exact preprocessing and limitations.

## Operation

`main.py` runs the manager. Use `--trip` to reach phones over mobile data instead of the trusted LAN. Owner and device access tokens are generated in `data/config.json`; the owner console uses the owner token, and each phone link carries its own per-vehicle token. The prototype uses HTTP and is intended for localhost or a trusted lab LAN, not public Internet deployment; per-device identity and TLS belong in a later phase. The manager and phone clocks should be synchronized, because timestamps determine trip membership and stale telemetry.

This is a desktop lab prototype. GPS maps, genuine IMU calibration, dedicated drowsiness detection and validation with live driving footage remain future work.
