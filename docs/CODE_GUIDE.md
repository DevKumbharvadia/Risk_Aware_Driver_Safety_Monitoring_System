# Explaining the project in the programming lab

## Architecture

```text
Driver phone (Chrome: camera + GPS + accelerometer + gyroscope)
                    |
              HTTPS JSON / JPEG frames
                    |
            MobileHandler -> VehicleLink (one per vehicle)
                    |
          TrainedDetector + FaceActivity + RiskEngine
                    |
               FleetServer + Store
                    |
                 SQLite database
                    |
          Owner Tkinter app (manager PC)

Optional preview JPEG -> server memory -> owner Live monitoring
```

A phone is a thin browser client: it captures frames and sensors and posts them to the manager PC. The manager classifies each frame, combines the prediction with phone GPS speed and motion, runs the temporal risk rules and stores the sample. Speed and acceleration come from the phone; the classifier does not infer eye closure or yawning, but the Face Landmarker supplies blink and head-direction cues.

## Project layout

```text
fleet/
  risk/        risk assessment engine — engine.py, attention.py
  perception/  driver perception — base.py, trained_model.py, face_activity.py, face_preview.py
  manager/     manager side — server.py, storage.py, network.py, owner_ui.py, phone_manager.py, ui_common.py
  mobile/      phone terminal — phone_speed.py, mobile.html
  tunnel/      Cloudflare tunnel — cloudflare.py
main.py        entry point
```

Dependencies point inward: `manager` uses `perception`, `risk`, `mobile` and `tunnel`; `perception` uses `risk`; `risk`, `mobile` and `tunnel` depend only on the standard library and their own assets.

## Read the code in this order

1. `fleet/risk/engine.py` and `fleet/risk/attention.py`: risk data model, input validation, temporal rules and speed-aware attention.
2. `fleet/perception/base.py` and `fleet/perception/trained_model.py`: the detector interface and the trained CPU classifier.
   `fleet/perception/face_activity.py` and `fleet/perception/face_preview.py`: face/head cues and preview annotation.
3. `fleet/manager/storage.py`: database schema, CRUD, transactional assignments, logs.
4. `fleet/manager/network.py`: one HTTP client method and a custom exception.
5. `fleet/manager/server.py`: URL routing, authorization, persistence.
6. `fleet/manager/phone_manager.py`: per-vehicle phone links, frame intake, risk and storage on the manager PC.
7. `fleet/manager/owner_ui.py`: sidebar pages, tables, dialogs, live monitoring, export.
8. `main.py`: the phone-camera manager entry point.

## Python concepts used for a reason

| Concept | Example and purpose |
| --- | --- |
| Variables, conditions, loops | Score thresholds, per-behavior duration checks, rendering table rows |
| Functions and methods | Small operations for assigning trips, applying filters and evaluating risk |
| Lists, tuples, dictionaries | Rows, rules, records, snapshots and JSON messages |
| Deque | Rolling history of yawning episodes |
| Data classes | Explicit fields in `Measurements` and `RiskResult` |
| Object-oriented programming | `Store`, `ApiClient`, `VehicleLink`, UI classes |
| Abstraction and polymorphism | `Detector.read()` implemented by the trained classifier |
| Composition | `VehicleLink` owns a risk engine and a face tracker; the manager owns the store and fleet server |
| Modules and packages | Separate storage, networking, UI and business rules |
| Exceptions | `ApiError`, validation errors and recoverable camera failures |
| Context managers | Database transactions, files and HTTP responses close reliably |
| File handling | Config JSON, CSV export, rotating diagnostic logs |
| SQLite | Relationships, constraints, indexes, transactions and parameterized queries |
| Threads and synchronization | HTTP workers, the phone terminal, locks around per-vehicle risk state |
| Queues and events | Workers communicate with the Tkinter main thread without modifying widgets |
| Inheritance | HTTP request handler and detector implementations |

We do not add advanced concepts merely to make the code look larger. For example, a generator or decorator is useful only when it simplifies a real responsibility. `@dataclass`, `@contextmanager`, and `@abstractmethod` already demonstrate purposeful decorators.

## Design principles

- **Single responsibility:** the risk engine computes risk, the store manages persistence, and UI classes manage widgets.
- **Separation of concerns:** widgets do not contain SQL; the server does not manipulate widgets.
- **Dependency injection:** constructors receive a store, API client or link, keeping collaborators swappable.
- **Open for extension:** the trained detector implements `read()` without redesigning the database. More detectors can use the same interface later.
- **Composition over unnecessary inheritance:** a link owns its collaborators rather than inheriting their behavior.
- **One source of truth:** trips and fleet records live on the server; the phone terminal streams to it.
- **Explicit limitations:** UNKNOWN and OFFLINE are distinct from LOW risk.

## Threading explanation

The manager PC runs two `ThreadingHTTPServer`s — the fleet API and the phone terminal — each on its own thread pool. A phone POST is handled by `MobileHandler`, which hands the frame to that vehicle's `VehicleLink`. A lock on each link prevents a frame from racing with assignment or risk-state changes. The Tkinter owner app runs on the main thread and refreshes by polling the fleet API; it never blocks on a phone frame.

## Database integrity explanation

Each trip references one vehicle, driver and route. Partial unique indexes prevent a vehicle or driver from appearing in two active trips. Changing an assignment is one transaction: either both ending the old trip and creating the new one succeed, or neither does. Historical names are copied into the trip at creation time. Sample UUIDs make delivery idempotent if a frame is resent.

## Suggested demonstration order

1. Explain the problem: a fleet owner needs actionable warnings and vehicle context.
2. Run `main.py` and introduce the owner dashboard and the **Connect a driver phone** window.
3. Open a vehicle's phone link on a phone, allow camera and location, and show the live class, score, speed and risk on the owner's **Live monitoring** page.
4. Trigger prolonged eye closure (or a looking-away posture) while moving and show the HIGH risk and the owner event; then show recovery and the below-3 km/h suppression.
5. Add a driver and change a trip; explain why earlier logs retain their old driver.
6. Filter logs by vehicle or driver and export CSV.
7. Run `--trip` to demonstrate a phone reaching the manager over mobile data.

For a live disconnection demonstration, stop the manager while a phone is connected, then restart it with the same data directory. The phone reconnects and resumes; samples captured during the gap are not attributed to the wrong trip.
