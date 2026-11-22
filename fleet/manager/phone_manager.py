
"""Phone-camera fleet manager.

Camera inference runs exclusively in the driver's smartphone browser
using MobileNetV3 Small ONNX.

The PC receives predictions and telemetry, validates them, runs the
risk engine, and stores the results.

The phone service listens only on localhost. Cloudflare Quick Tunnel
provides the public HTTPS URL used by drivers.
"""

from datetime import datetime, timezone
import json
import logging
import math
from pathlib import Path
import secrets
import threading
import time
import uuid
import tkinter as tk
from tkinter import ttk
from http.server import ThreadingHTTPServer
from urllib.parse import urlsplit

from .network import ApiClient
from .owner_ui import OwnerApp
from ..mobile.phone_speed import PhoneHandler, PhoneSpeed
from ..perception.trained_model import prediction_from_payload
from ..risk.engine import Measurements, RiskEngine
from ..tunnel.cloudflare import trip_proxy
from .server import FleetServer
from .storage import Store, utc_now


PROJECT_ROOT = Path(__file__).resolve().parents[2]

MOBILE_PAGE = PROJECT_ROOT / "fleet" / "mobile" / "mobile.html"

MOBILE_MODEL = (
    PROJECT_ROOT
    / "models"
    / "driver_mobilenetv3_small.onnx"
)

MAX_PREDICTION_BYTES = 32_000
MAX_PREVIEW_BYTES = 250_000

PREDICTION_MAX_AGE = 5.0
PREDICTION_FUTURE_TOLERANCE = 1.0
PREDICTION_STALE_OVERLAY = 2.5


def validate_mobile_assets():
    """Validate the browser page and ONNX model before starting."""

    if not MOBILE_PAGE.is_file():
        raise FileNotFoundError(
            f"Mobile page not found: {MOBILE_PAGE}"
        )

    if not MOBILE_MODEL.is_file():
        raise FileNotFoundError(
            "ONNX model not found.\n"
            f"Expected location: {MOBILE_MODEL}\n"
            "Place driver_mobilenetv3_small.onnx inside the "
            "project's models directory."
        )

    model_size = MOBILE_MODEL.stat().st_size

    if model_size <= 0:
        raise ValueError(
            f"ONNX model file is empty: {MOBILE_MODEL}"
        )

    logging.info("Mobile page: %s", MOBILE_PAGE)

    logging.info(
        "Browser ONNX model: %s (%.2f MB)",
        MOBILE_MODEL,
        model_size / (1024 * 1024),
    )


def behavior_label(behavior, confidence, face_activity, handset_visible):
    """Create a readable behavior label."""

    if handset_visible:
        return "PHONE USE"

    if behavior:
        return str(behavior).replace("_", " ").upper()

    return "UNKNOWN"


def classifier_summary(label, score, handset_visible):
    """Create a readable classifier summary."""

    if handset_visible:
        return "Phone detected"

    if label is None:
        return "No prediction"

    if score is None:
        return str(label)

    return f"{label} ({float(score):.1%})"


class PreviewTracker:
    """Basic JPEG preview handler without face detection."""

    def annotate(self, image_bytes, level):
        """Return the original JPEG and no bounding box."""

        return image_bytes, None


def apply_vehicle_speed(readings, data):
    """Apply validated phone GPS data to Measurements."""

    gps = PhoneSpeed()
    fix = {}

    if data.get("gps"):
        try:
            fix = data["gps"]

            captured = data.get("captured")
            server_capture = data.get("server_capture")

            if (
                not isinstance(captured, (int, float))
                or isinstance(captured, bool)
                or not math.isfinite(captured)
                or not isinstance(server_capture, (int, float))
                or isinstance(server_capture, bool)
                or not math.isfinite(server_capture)
            ):
                raise ValueError("Invalid GPS capture timestamp")

            gps_age = captured - fix["timestamp"]

            adjusted_timestamp = (
                time.time()
                - gps_age
                - max(
                    0.0,
                    time.monotonic() - server_capture,
                )
            )

            gps.accept({
                **fix,
                "timestamp": adjusted_timestamp,
            })

        except (
            ValueError,
            KeyError,
            TypeError,
            OverflowError,
        ):
            fix = {}

    gps.apply(readings)

    missing = readings.assessment_note.startswith(
        ("Phone GPS", "Waiting for phone GPS")
    )

    readings.speed_method = (
        "unavailable"
        if missing
        else (
            "GPS estimate"
            if fix.get("estimated")
            else "GPS"
        )
    )

    if missing:
        messages = {
            "denied": (
                "Allow precise location for this site "
                "in the phone browser."
            ),
            "timeout": (
                "GPS timed out. Try outdoors with precise "
                "location enabled."
            ),
            "unavailable": (
                "Location unavailable. Check phone location settings."
            ),
            "estimating": (
                "Waiting for sufficiently accurate movement "
                "to estimate speed."
            ),
        }

        readings.assessment_note = messages.get(
            data.get("gps_status"),
            readings.assessment_note,
        )


class VehicleLink:
    """Authenticated connection and assessment state for one vehicle."""

    def __init__(self, vehicle):
        self.vehicle = vehicle
        self.lock = threading.Lock()
        self.engine = RiskEngine()
        self.trip_id = None
        self.previous = 0.0

        self.tracker = PreviewTracker()
        self.overlay = (None, 0.0, "UNKNOWN")

    def receive_prediction(self, fleet, data, stopping_event):
        """Receive a browser ONNX prediction and assess it on the PC."""

        with self.lock:
            if stopping_event.is_set():
                raise RuntimeError(
                    "The manager is shutting down."
                )

            if not isinstance(data, dict):
                raise ValueError(
                    "Prediction payload must be a JSON object."
                )

            trip = fleet.store.assignment(self.vehicle)

            if not trip:
                raise ValueError(
                    "Ask the manager to assign this vehicle first."
                )

            now = time.monotonic()
            server_capture = data.get("server_capture")

            if (
                not isinstance(server_capture, (int, float))
                or isinstance(server_capture, bool)
                or not math.isfinite(server_capture)
            ):
                raise ValueError(
                    "Invalid prediction timestamp."
                )

            age = now - server_capture

            if not (
                -PREDICTION_FUTURE_TOLERANCE
                <= age
                <= PREDICTION_MAX_AGE
            ):
                raise ValueError(
                    "Delayed prediction. Reconnecting to the manager…"
                )

            readings = prediction_from_payload(data)

            if stopping_event.is_set():
                raise RuntimeError(
                    "The manager is shutting down."
                )

            apply_vehicle_speed(readings, data)

            readings.accelerometer = data.get("accelerometer")
            readings.gyroscope = data.get("gyroscope")

            readings = Measurements.from_dict(
                readings.to_dict()
            )

            if stopping_event.is_set():
                raise RuntimeError(
                    "The manager is shutting down."
                )

            gap = (
                now - self.previous
                if self.previous
                else 0.0
            )

            if trip["id"] != self.trip_id or gap > 3.0:
                self.engine = RiskEngine()
                gap = 0.0

            gap = max(0.0, min(2.0, gap))

            self.trip_id = trip["id"]
            self.previous = now

            risk = self.engine.update(readings, gap)

            self.overlay = (
                trip["id"],
                time.monotonic(),
                risk.level,
            )

            fleet.store.add_sample({
                "id": str(uuid.uuid4()),
                "vehicle_id": self.vehicle,
                "trip_id": trip["id"],
                "captured_at": utc_now(),
                "readings": readings.to_dict(),
                "risk": risk.to_dict(),
            })

            if stopping_event.is_set():
                raise RuntimeError(
                    "The manager is shutting down."
                )

            return {
                "driver": trip["driver_name"],
                "route": trip["route_name"],
                "mount_note": (
                    "Head-pose calibration is not available "
                    "in the single-model browser configuration."
                ),
                "calibration_id": None,
                "label": behavior_label(
                    readings.behavior,
                    readings.confidence,
                    readings.face_activity,
                    readings.handset_visible,
                ),
                "behavior": readings.behavior,
                "confidence": readings.confidence,
                "raw_label": readings.classifier_label,
                "raw_score": readings.classifier_score,
                "prediction": classifier_summary(
                    readings.classifier_label,
                    readings.classifier_score,
                    readings.handset_visible,
                ),
                "handset": None,
                "risk": risk.level,
                "reason": risk.reason,
                "trip_id": trip["id"],
                "speed_method": readings.speed_method,
                "speed": (
                    None
                    if readings.speed_method == "unavailable"
                    else readings.speed
                ),
                "assessment_available": (
                    readings.assessment_available
                ),
                "assessment_note": readings.assessment_note,
                "inference_ms": readings.inference_ms,
            }


class MobileHandler(PhoneHandler):
    """HTTP endpoints used by the smartphone browser."""

    def _stopping(self):
        return self.server.stopping.is_set()

    def _get_vehicle_link(self):
        """Authenticate a phone request using its vehicle token."""

        token = self.headers.get(
            "Authorization",
            "",
        ).removeprefix("Bearer ").strip()

        if not token:
            return None

        return self.server.links.get(token)

    def do_GET(self):

        if self._stopping():
            return self.respond(
                503,
                b"Fleet Guardian is shutting down.",
            )

        path = urlsplit(self.path).path

        if path == "/preview-control":

            link = self._get_vehicle_link()

            if not link:
                return self.respond(
                    403,
                    b"Open the current vehicle link from the manager PC.",
                )

            fleet = self.server.fleet
            trip = fleet.store.assignment(link.vehicle)

            enabled = bool(
                trip
                and fleet.preview_is_selected(link.vehicle)
            )

            payload = json.dumps({
                "enabled": enabled,
            }).encode("utf-8")

            return self.respond(
                200,
                payload,
                "application/json",
            )

        if path == "/version":
            return self.respond(
                200,
                b'{"mobile":7,"inference":"browser-onnx"}',
                "application/json",
            )

        if path == "/clock":
            payload = json.dumps({
                "monotonic": time.monotonic(),
            }).encode("utf-8")

            return self.respond(
                200,
                payload,
                "application/json",
            )

        if path == "/models/driver_mobilenetv3_small.onnx":

            if not MOBILE_MODEL.is_file():
                logging.error(
                    "ONNX model file not found: %s",
                    MOBILE_MODEL,
                )

                return self.respond(
                    404,
                    b"ONNX model not found. Check the models directory.",
                )

            try:
                model = MOBILE_MODEL.read_bytes()

            except OSError:
                logging.exception(
                    "Unable to read ONNX model"
                )

                return self.respond(
                    500,
                    b"Unable to read ONNX model.",
                )

            return self.respond(
                200,
                model,
                "application/octet-stream",
            )

        if path != "/":
            return self.respond(
                404,
                b"Unknown page",
            )

        try:
            page = MOBILE_PAGE.read_bytes()

        except OSError:
            logging.exception(
                "Could not read the mobile page"
            )

            return self.respond(
                500,
                b"Mobile page unavailable.",
            )

        return self.respond(
            200,
            page,
            "text/html; charset=utf-8",
        )

    def do_POST(self):

        if self._stopping():
            return self.respond(
                503,
                b"Fleet Guardian is shutting down.",
            )

        try:
            path = urlsplit(self.path).path

            if path not in ("/prediction", "/preview"):
                return self.respond(
                    404,
                    b"Unknown endpoint",
                )

            link = self._get_vehicle_link()

            if not link:
                return self.respond(
                    403,
                    b"Open the current vehicle link from the manager PC.",
                )

            size_header = self.headers.get(
                "Content-Length",
                "",
            )

            try:
                size = int(size_header)

            except (ValueError, TypeError):
                raise ValueError(
                    "Invalid request size"
                )

            maximum = (
                MAX_PREVIEW_BYTES
                if path == "/preview"
                else MAX_PREDICTION_BYTES
            )

            if not 0 < size <= maximum:
                raise ValueError(
                    "Invalid request size"
                )

            self.connection.settimeout(5)
            body = self.rfile.read(size)

            if len(body) != size:
                raise ValueError(
                    "Incomplete phone request"
                )

            if self._stopping():
                return self.respond(
                    503,
                    b"Fleet Guardian is shutting down.",
                )

            if path == "/preview":

                fleet = self.server.fleet

                if not fleet.preview_is_selected(link.vehicle):
                    return self.respond(
                        403,
                        b"Camera preview is not enabled for this vehicle.",
                    )

                trip = fleet.store.assignment(link.vehicle)

                if (
                    not trip
                    or str(trip["id"]) != self.headers.get("X-Trip")
                ):
                    raise ValueError(
                        "Trip changed"
                    )

                if (
                    not body.startswith(b"\xff\xd8")
                    or not body.endswith(b"\xff\xd9")
                ):
                    raise ValueError(
                        "Invalid JPEG preview"
                    )

                assessed_trip, assessed_at, level = link.overlay

                if (
                    assessed_trip != trip["id"]
                    or time.monotonic() - assessed_at
                    > PREDICTION_STALE_OVERLAY
                ):
                    level = "UNKNOWN"

                annotated, box = link.tracker.annotate(
                    body,
                    level,
                )

                if self._stopping():
                    return self.respond(
                        503,
                        b"Fleet Guardian is shutting down.",
                    )

                with fleet.frame_lock:

                    if not fleet.preview_is_selected(link.vehicle):
                        return self.respond(
                            403,
                            b"Camera preview selection has changed.",
                        )

                    current_trip = fleet.store.assignment(
                        link.vehicle
                    )

                    if (
                        not current_trip
                        or current_trip["id"] != trip["id"]
                    ):
                        return self.respond(
                            409,
                            b"Vehicle trip changed during preview upload.",
                        )

                    fleet.frames[link.vehicle] = (
                        datetime.now(timezone.utc),
                        annotated,
                        trip["id"],
                    )

                return self.respond(
                    200,
                    json.dumps({
                        "box": box,
                        "level": level,
                    }).encode("utf-8"),
                    "application/json",
                )

            try:
                data = json.loads(body)

            except (
                json.JSONDecodeError,
                UnicodeDecodeError,
            ):
                raise ValueError(
                    "Invalid JSON prediction payload"
                )

            if not isinstance(data, dict):
                raise ValueError(
                    "Prediction must be a JSON object"
                )

            result = link.receive_prediction(
                self.server.fleet,
                data,
                self.server.stopping,
            )

            if self._stopping():
                return

            return self.respond(
                200,
                json.dumps(result).encode("utf-8"),
                "application/json",
            )

        except TimeoutError as error:

            logging.warning(
                "Phone request timed out: %s",
                error,
            )

            if not self._stopping():
                return self.respond(
                    408,
                    str(error).encode("utf-8"),
                )

        except (
            ValueError,
            KeyError,
            TypeError,
            OSError,
            OverflowError,
        ) as error:

            if not self._stopping():
                logging.warning(
                    "Phone request rejected: %s",
                    error,
                )

                return self.respond(
                    400,
                    str(error).encode("utf-8"),
                )

        except RuntimeError as error:

            if not self._stopping():
                logging.info(
                    "Phone request ended: %s",
                    error,
                )

                return self.respond(
                    503,
                    str(error).encode("utf-8"),
                )

        except Exception:

            if not self._stopping():
                logging.exception(
                    "Phone prediction or preview request failed"
                )

                return self.respond(
                    500,
                    b"Prediction or fleet service unavailable. Check PC setup.",
                )


def run_manager(args, config):
    """Start Fleet Guardian with Cloudflare Quick Tunnel."""

    data = args.data_dir

    logging.info(
        "Fleet Guardian starting in Cloudflare Quick Tunnel mode."
    )

    validate_mobile_assets()

    store = Store(data / "fleet.sqlite3")
    store.seed()

    fleet = FleetServer(
        ("127.0.0.1", 0),
        store,
        config["owner_token"],
        config["device_token"],
    )

    mobile_server = ThreadingHTTPServer(
        ("127.0.0.1", 0),
        MobileHandler,
    )

    mobile_server.daemon_threads = False
    mobile_server.block_on_close = True
    mobile_server.stopping = threading.Event()

    with (
        fleet,
        mobile_server,
        trip_proxy(mobile_server.server_port) as base_url,
    ):

        logging.info(
            "Cloudflare phone service ready at %s",
            base_url,
        )

        print("\n" + "=" * 68, flush=True)

        print(
            "FLEET GUARDIAN — CLOUDFLARE QUICK TUNNEL READY",
            flush=True,
        )

        print(
            f"Public phone service: {base_url}",
            flush=True,
        )

        print(
            "Browser-side ONNX inference enabled.",
            flush=True,
        )

        print(
            "Copy the vehicle-specific links from the Connect a driver phone window.",
            flush=True,
        )

        print("=" * 68 + "\n", flush=True)

        mobile_server.fleet = fleet
        mobile_server.links = {}

        mobile_thread = threading.Thread(
            target=mobile_server.serve_forever,
            name="fleet-mobile-http",
            daemon=True,
        )

        fleet_thread = threading.Thread(
            target=fleet.serve_forever,
            name="fleet-owner-http",
            daemon=True,
        )

        mobile_thread.start()
        fleet_thread.start()

        root = tk.Tk()

        OwnerApp(
            root,
            ApiClient(
                f"http://127.0.0.1:{fleet.server_port}",
                config["owner_token"],
            ),
        )

        pairing = tk.Toplevel(root)
        pairing.title("Connect a driver phone")

        ttk.Label(
            pairing,
            text=(
                "Send the Cloudflare phone link to the driver. "
                "Open it in Chrome using mobile data or another network."
            ),
        ).pack(
            padx=12,
            pady=8,
        )

        table = ttk.Frame(pairing)

        table.pack(
            fill="both",
            padx=12,
            pady=8,
        )

        tokens = {}

        def refresh():

            for child in table.winfo_children():
                child.destroy()

            for vehicle in store.snapshot()["vehicles"]:

                vehicle_id = vehicle["id"]

                if vehicle_id not in tokens:

                    token = secrets.token_urlsafe(20)
                    tokens[vehicle_id] = token

                    mobile_server.links[token] = VehicleLink(
                        vehicle_id
                    )

                url = f"{base_url}/#{tokens[vehicle_id]}"

                row = ttk.Frame(table)
                row.pack(fill="x")

                ttk.Label(
                    row,
                    text=vehicle["registration"],
                    width=18,
                ).pack(side="left")

                def copy(value=url):
                    root.clipboard_clear()
                    root.clipboard_append(value)

                ttk.Button(
                    row,
                    text="Copy phone link",
                    command=copy,
                ).pack(side="left")

        refresh()

        ttk.Button(
            pairing,
            text="Refresh vehicle list",
            command=refresh,
        ).pack(pady=6)

        pairing.protocol(
            "WM_DELETE_WINDOW",
            pairing.iconify,
        )

        shutdown_lock = threading.Lock()
        shutdown_started = False

        def shutdown():

            nonlocal shutdown_started

            with shutdown_lock:

                if shutdown_started:
                    return

                shutdown_started = True

            logging.info(
                "Fleet Guardian shutdown requested."
            )

            fleet.select_preview(None)

            mobile_server.stopping.set()

            mobile_server.shutdown()
            fleet.shutdown()

            try:

                if root.winfo_exists():
                    root.destroy()

            except tk.TclError:
                pass

        root.protocol(
            "WM_DELETE_WINDOW",
            shutdown,
        )

        logging.info(
            "Fleet Guardian ready; waiting for owner dashboard and phones."
        )

        try:
            root.mainloop()

        finally:
            shutdown()
