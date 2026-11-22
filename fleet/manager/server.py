
"""Local fleet server. Interfaces never access SQLite directly."""

from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import hmac
import json
import logging
import sqlite3
import threading
import time
from urllib.parse import parse_qs, urlparse


class FleetServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, store, owner_token, device_token):
        super().__init__(address, Handler)

        self.store = store
        self.owner_token = str(owner_token)
        self.device_token = str(device_token)

        self.frames = {}
        self.frame_lock = threading.RLock()

        self.preview_selection_lock = threading.Lock()
        self.preview_vehicle_id = None
        self.preview_selection_updated = 0.0
        self.preview_selection_ttl = 4.5

        self.detector = None
        self.model_lock = threading.Lock()

    def select_preview(self, vehicle_id):
        """Select a vehicle or release the preview."""
        with self.preview_selection_lock:
            changed = self.preview_vehicle_id != vehicle_id

            self.preview_vehicle_id = vehicle_id
            self.preview_selection_updated = (
                time.monotonic() if vehicle_id is not None else 0.0
            )

        if changed:
            with self.frame_lock:
                self.frames.clear()

    def preview_is_selected(self, vehicle_id):
        """Check and expire the selected vehicle's preview lease."""
        expired = False

        with self.preview_selection_lock:
            active = (
                vehicle_id is not None
                and self.preview_vehicle_id == vehicle_id
                and time.monotonic() - self.preview_selection_updated
                <= self.preview_selection_ttl
            )

            if self.preview_vehicle_id is not None and not active:
                self.preview_vehicle_id = None
                self.preview_selection_updated = 0.0
                expired = True

        if expired:
            with self.frame_lock:
                self.frames.clear()

        return active

    def classify(self, jpeg):
        """Legacy classifier; phone inference runs in the browser."""
        from PIL import Image
        import numpy as np

        from ..perception.trained_model import (
            DEFAULT_MODEL,
            TrainedDetector,
        )

        with Image.open(BytesIO(jpeg)) as picture:
            if picture.format != "JPEG" or max(picture.size) > 1024:
                raise ValueError(
                    "Expected a JPEG up to 1024 pixels per side."
                )

            bgr = np.asarray(
                picture.convert("RGB")
            )[:, :, ::-1]

        with self.model_lock:
            if self.detector is None:
                self.detector = TrainedDetector(
                    getattr(self, "model_path", DEFAULT_MODEL)
                )

            return self.detector.read(bgr)


class Handler(BaseHTTPRequestHandler):
    server_version = "FleetLab/1.0"

    OWNER_PATHS = {
        "/snapshot",
        "/logs",
        "/entity",
        "/delete-entity",
        "/assign",
        "/end-trip",
        "/preview-selection",
    }

    MAX_BODY_SIZE = 400_000

    def log_message(self, format_string, *args):
        logging.debug(format_string, *args)

    def respond(self, status, data, content_type="application/json"):
        if content_type == "application/json":
            body = json.dumps(data).encode("utf-8")
        else:
            body = data

        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        self.dispatch(False)

    def do_POST(self):
        self.dispatch(True)

    def authenticate(self):
        """Return 'owner', 'device', or None."""
        authorization = self.headers.get("Authorization", "")

        if not authorization.startswith("Bearer "):
            return None

        token = authorization[7:].strip()

        if not token:
            return None

        owner = hmac.compare_digest(token, self.server.owner_token)
        device = hmac.compare_digest(token, self.server.device_token)

        if owner:
            return "owner"

        if device:
            return "device"

        return None

    def dispatch(self, posting):
        try:
            url = urlparse(self.path)
            path = url.path

            if posting:
                raw_size = self.headers.get("Content-Length")

                if raw_size is None:
                    raise ValueError("Missing request body length.")

                try:
                    size = int(raw_size)
                except (TypeError, ValueError):
                    raise ValueError("Invalid request body length.")

                if not 0 < size <= self.MAX_BODY_SIZE:
                    raise ValueError("Request is empty or too large.")

                self.connection.settimeout(5)
                body = self.rfile.read(size)

                if len(body) != size:
                    raise ValueError("Incomplete request body.")

            access = self.authenticate()

            if access is None:
                self.respond(
                    401,
                    {"error": "Incorrect or missing access token."},
                )
                return

            owner_only = (
                path in self.OWNER_PATHS
                or path.startswith("/frame/")
            )

            if owner_only and access != "owner":
                self.respond(
                    403,
                    {"error": "Owner access required."},
                )
                return

            if posting:
                try:
                    data = json.loads(body.decode("utf-8"))
                except (ValueError, UnicodeError):
                    raise ValueError("Invalid JSON request body.")

                if not isinstance(data, dict):
                    raise ValueError("Expected a JSON object.")

                self.post_route(path, data)

            else:
                self.get_route(path, parse_qs(url.query))

        except (
            ValueError,
            KeyError,
            TypeError,
            sqlite3.IntegrityError,
        ) as error:
            message = str(error)

            if isinstance(error, sqlite3.IntegrityError):
                message = (
                    "Duplicate or invalid record. Registration, "
                    "license, and route names must be unique."
                )

            self.respond(400, {"error": message})

        except (
            BrokenPipeError,
            ConnectionResetError,
            TimeoutError,
        ):
            pass

        except Exception:
            logging.exception("Server request failed")

            try:
                self.respond(
                    500,
                    {"error": "Server error. See the server log."},
                )
            except (
                BrokenPipeError,
                ConnectionResetError,
                TimeoutError,
            ):
                pass

    def get_route(self, path, query):
        store = self.server.store

        if path == "/snapshot":
            self.respond(200, store.snapshot())

        elif path == "/logs":
            filters = {
                key: values[0]
                for key, values in query.items()
                if key in (
                    "vehicle_id",
                    "driver_id",
                    "level",
                    "since",
                    "until",
                )
            }

            self.respond(200, store.logs(**filters))

        elif path.startswith("/frame/"):
            try:
                vehicle_id = int(path.split("/")[-1])
            except ValueError:
                raise ValueError("Invalid vehicle ID.")

            if not self.server.preview_is_selected(vehicle_id):
                self.respond(
                    404,
                    {"error": "Vehicle is not selected for preview."},
                )
                return

            with self.server.frame_lock:
                if not self.server.preview_is_selected(vehicle_id):
                    self.respond(
                        404,
                        {"error": "Preview selection changed."},
                    )
                    return

                frame = self.server.frames.get(vehicle_id)

            trip = store.assignment(vehicle_id)

            if (
                not frame
                or not trip
                or frame[2] != trip["id"]
                or (
                    datetime.now(timezone.utc) - frame[0]
                ).total_seconds() > 6
            ):
                self.respond(
                    404,
                    {"error": "No recent camera frame."},
                )
            else:
                self.respond(
                    200,
                    frame[1],
                    "image/jpeg",
                )

        else:
            self.respond(404, {"error": "Unknown endpoint."})

    def post_route(self, path, data):
        store = self.server.store

        if path == "/preview-selection":
            vehicle_id = data.get("vehicle_id")

            if vehicle_id is not None:
                if isinstance(vehicle_id, bool):
                    raise ValueError("Invalid vehicle selection.")

                try:
                    vehicle_id = int(vehicle_id)
                except (TypeError, ValueError):
                    raise ValueError("Invalid vehicle selection.")

                vehicles = store.snapshot().get("vehicles", [])
                valid_ids = {
                    int(vehicle["id"])
                    for vehicle in vehicles
                }

                if vehicle_id not in valid_ids:
                    raise ValueError("Selected vehicle does not exist.")

                if not store.assignment(vehicle_id):
                    vehicle_id = None

            self.server.select_preview(vehicle_id)

            self.respond(
                200,
                {
                    "ok": True,
                    "vehicle_id": vehicle_id,
                },
            )

        elif path == "/entity":
            record_id = store.save_entity(
                data["kind"],
                data["values"],
            )
            self.respond(200, {"id": record_id})

        elif path == "/delete-entity":
            store.delete_entity(
                data["kind"],
                int(data["id"]),
            )
            self.respond(200, {"ok": True})

        elif path == "/assign":
            trip_id = store.assign(
                int(data["vehicle_id"]),
                int(data["driver_id"]),
                int(data["route_id"]),
            )
            self.respond(200, {"trip_id": trip_id})

        elif path == "/end-trip":
            store.end_trip(int(data["trip_id"]))
            self.respond(200, {"ok": True})

        else:
            self.respond(404, {"error": "Unknown endpoint."})
