
"""Local fleet server. Interfaces never access SQLite directly."""

from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import hmac
import json
import logging
import re
import sqlite3
import threading
import time
from urllib.parse import parse_qs, urlparse


SESSION_ID_PATTERN = re.compile(r"^[a-f0-9]{32}$")


def _reject_json_constant(value):
    """Reject non-standard JSON values such as NaN and Infinity."""

    raise ValueError(f"Invalid JSON numeric value: {value}")


class FleetServer(ThreadingHTTPServer):
    """Manage fleet storage, phone sessions and camera previews."""

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
        self.preview_session_id = None
        self.preview_selection_updated = 0.0
        self.preview_selection_ttl = 4.5

        self.mobile_sessions = {}
        self.mobile_sessions_lock = threading.Lock()

        self.detector = None
        self.model_lock = threading.Lock()

    @staticmethod
    def valid_session_id(session_id):
        """Validate a UUID-hex phone session ID."""

        return (
            isinstance(session_id, str)
            and SESSION_ID_PATTERN.fullmatch(session_id) is not None
        )

    def select_preview(self, session_id):
        """Select one phone preview or clear the selection."""

        if session_id is not None:
            if not isinstance(session_id, str):
                raise ValueError("Invalid phone session ID.")

            session_id = session_id.strip()

            if not self.valid_session_id(session_id):
                raise ValueError("Invalid phone session ID.")

        with self.preview_selection_lock:
            changed = self.preview_session_id != session_id

            self.preview_session_id = session_id

            self.preview_selection_updated = (
                time.monotonic() if session_id else 0.0
            )

        if changed:
            with self.frame_lock:
                self.frames.clear()

    def preview_is_selected(self, session_id):
        """Check and refresh the selected phone's preview lease."""

        if not self.valid_session_id(session_id):
            return False

        expired = False
        now = time.monotonic()

        with self.preview_selection_lock:

            if self.preview_session_id == session_id:

                age = now - self.preview_selection_updated

                if 0 <= age <= self.preview_selection_ttl:
                    self.preview_selection_updated = now
                    active = True

                else:
                    self.preview_session_id = None
                    self.preview_selection_updated = 0.0
                    expired = True
                    active = False

            else:
                active = False

        if expired:
            with self.frame_lock:
                self.frames.clear()

        return active

    def classify(self, jpeg):
        """Legacy classifier; current inference runs on the phone."""

        from PIL import Image
        import numpy as np

        from ..perception.trained_model import (
            DEFAULT_MODEL,
            TrainedDetector,
        )

        if not isinstance(jpeg, bytes) or not jpeg:
            raise ValueError("Invalid JPEG image data.")

        with Image.open(BytesIO(jpeg)) as picture:

            if (
                picture.format != "JPEG"
                or len(picture.size) != 2
                or min(picture.size) <= 0
                or max(picture.size) > 1024
            ):
                raise ValueError(
                    "Expected a JPEG up to 1024 pixels per side."
                )

            picture.load()

            rgb = np.asarray(
                picture.convert("RGB")
            )

            bgr = np.ascontiguousarray(
                rgb[:, :, ::-1]
            )

        with self.model_lock:

            if self.detector is None:
                self.detector = TrainedDetector(
                    getattr(self, "model_path", DEFAULT_MODEL)
                )

            return self.detector.read(bgr)


class Handler(BaseHTTPRequestHandler):
    """Authenticated HTTP API for the owner dashboard."""

    server_version = "FleetLab/1.0"
    sys_version = ""

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
    REQUEST_TIMEOUT = 5

    def log_message(self, format_string, *args):
        logging.debug(format_string, *args)

    def respond(self, status, data, content_type="application/json"):
        """Send an HTTP response without caching."""

        try:
            if content_type == "application/json":
                body = json.dumps(
                    data,
                    allow_nan=False,
                ).encode("utf-8")
            else:
                if not isinstance(data, bytes):
                    raise TypeError(
                        "Non-JSON HTTP response data must be bytes."
                    )

                body = data

            self.send_response(status)

            self.send_header(
                "Content-Type",
                content_type,
            )

            self.send_header(
                "Content-Length",
                str(len(body)),
            )

            self.send_header(
                "Cache-Control",
                "no-store",
            )

            self.send_header(
                "X-Content-Type-Options",
                "nosniff",
            )

            self.send_header(
                "X-Frame-Options",
                "DENY",
            )

            self.send_header(
                "Referrer-Policy",
                "no-referrer",
            )

            self.end_headers()

            self.wfile.write(body)

        except (
            BrokenPipeError,
            ConnectionResetError,
            ConnectionAbortedError,
            TimeoutError,
        ):
            logging.debug(
                "Client disconnected before receiving the response."
            )

        except OSError:
            logging.debug(
                "HTTP response could not be delivered.",
                exc_info=True,
            )

    def do_GET(self):
        """Handle dashboard GET requests."""

        self.dispatch(False)

    def do_POST(self):
        """Handle dashboard POST requests."""

        self.dispatch(True)

    def authenticate(self):
        """Return the authenticated role or None."""

        authorization = self.headers.get("Authorization", "")

        if not authorization.startswith("Bearer "):
            return None

        token = authorization[7:].strip()

        if not token:
            return None

        if hmac.compare_digest(token, self.server.owner_token):
            return "owner"

        if hmac.compare_digest(token, self.server.device_token):
            return "device"

        return None

    def dispatch(self, posting):
        """Authenticate, validate and route an HTTP request."""

        try:
            url = urlparse(self.path)
            path = url.path

            if url.scheme or url.netloc or url.fragment:
                return self.respond(
                    400,
                    {"error": "Invalid request URL."},
                )

            access = self.authenticate()

            if access is None:
                return self.respond(
                    401,
                    {"error": "Incorrect or missing access token."},
                )

            owner_only = (
                path in self.OWNER_PATHS
                or path.startswith("/frame/")
            )

            if owner_only and access != "owner":
                return self.respond(
                    403,
                    {"error": "Owner access required."},
                )

            if posting:

                data = self.read_json_body()

                return self.post_route(
                    path,
                    data,
                )

            return self.get_route(
                path,
                parse_qs(url.query),
            )

        except (
            ValueError,
            KeyError,
            TypeError,
            sqlite3.IntegrityError,
        ) as error:

            if isinstance(error, sqlite3.IntegrityError):
                message = (
                    "Duplicate or invalid record. Registration, "
                    "license, and route names must be unique."
                )
            else:
                message = str(error)

            self.respond(
                400,
                {"error": message},
            )

        except (
            BrokenPipeError,
            ConnectionResetError,
            ConnectionAbortedError,
            TimeoutError,
        ):
            logging.debug(
                "Client disconnected during request processing."
            )

        except sqlite3.Error:
            logging.exception(
                "Database operation failed."
            )

            self.respond(
                500,
                {"error": "Database operation failed. See server log."},
            )

        except Exception:
            logging.exception(
                "Server request failed."
            )

            self.respond(
                500,
                {"error": "Server error. See the server log."},
            )

    def read_json_body(self):
        """Read and validate a bounded JSON request body."""

        raw_size = self.headers.get("Content-Length")

        if raw_size is None:
            raise ValueError(
                "Missing request body length."
            )

        try:
            size = int(raw_size)

        except (TypeError, ValueError):
            raise ValueError(
                "Invalid request body length."
            ) from None

        if not 0 < size <= self.MAX_BODY_SIZE:
            raise ValueError(
                "Request is empty or too large."
            )

        self.connection.settimeout(
            self.REQUEST_TIMEOUT
        )

        body = self.rfile.read(size)

        if len(body) != size:
            raise ValueError(
                "Incomplete request body."
            )

        try:
            data = json.loads(
                body.decode("utf-8"),
                parse_constant=_reject_json_constant,
            )

        except (ValueError, UnicodeError):
            raise ValueError(
                "Invalid JSON request body."
            ) from None

        if not isinstance(data, dict):
            raise ValueError(
                "Expected a JSON object."
            )

        return data

    def get_route(self, path, query):
        """Handle dashboard GET requests."""

        store = self.server.store

        if path == "/snapshot":
            return self.respond(
                200,
                store.snapshot(),
            )

        if path == "/logs":

            filters = {
                key: values[0]
                for key, values in query.items()
                if values and key in {
                    "vehicle_id",
                    "driver_id",
                    "level",
                    "since",
                    "until",
                }
            }

            return self.respond(
                200,
                store.logs(**filters),
            )

        if path.startswith("/frame/"):
            return self.get_frame(path)

        return self.respond(
            404,
            {"error": "Unknown endpoint."},
        )

    def get_frame(self, path):
        """Return only the selected phone session's latest frame."""

        session_id = path[len("/frame/"):].strip()

        if not self.server.valid_session_id(session_id):
            raise ValueError(
                "Invalid phone session ID."
            )

        if not self.server.preview_is_selected(session_id):
            return self.respond(
                404,
                {"error": "Phone session is not selected for preview."},
            )

        with self.server.mobile_sessions_lock:
            link = self.server.mobile_sessions.get(session_id)

        if link is None:
            return self.respond(
                404,
                {"error": "Phone session no longer exists."},
            )

        with self.server.frame_lock:
            frame = self.server.frames.get(session_id)

        if not self.server.preview_is_selected(session_id):
            return self.respond(
                404,
                {"error": "Preview selection changed."},
            )

        trip = self.server.store.assignment(
            link.vehicle
        )

        if not frame or not trip:
            return self.respond(
                404,
                {"error": "No recent camera frame for this phone."},
            )

        try:
            frame_time, image_bytes, frame_trip_id = frame

            if not isinstance(frame_time, datetime):
                raise ValueError("Invalid frame timestamp.")

            if (
                frame_time.tzinfo is None
                or frame_time.utcoffset() is None
            ):
                raise ValueError("Frame timestamp has no timezone.")

            age = (
                datetime.now(timezone.utc) - frame_time
            ).total_seconds()

        except (TypeError, ValueError, OverflowError):
            age = float("inf")
            image_bytes = None
            frame_trip_id = None

        if (
            age < 0
            or age > 6
            or frame_trip_id != trip["id"]
            or not isinstance(image_bytes, bytes)
            or not image_bytes
        ):

            with self.server.frame_lock:

                if self.server.frames.get(session_id) is frame:
                    self.server.frames.pop(
                        session_id,
                        None,
                    )

            return self.respond(
                404,
                {"error": "No recent camera frame for this phone."},
            )

        return self.respond(
            200,
            image_bytes,
            "image/jpeg",
        )

    def post_route(self, path, data):
        """Handle dashboard POST requests."""

        store = self.server.store

        if path == "/preview-selection":
            return self.set_preview_selection(data)

        if path == "/entity":

            if "kind" not in data or "values" not in data:
                raise ValueError(
                    "Missing entity information."
                )

            record_id = store.save_entity(
                data["kind"],
                data["values"],
            )

            return self.respond(
                200,
                {"id": record_id},
            )

        if path == "/delete-entity":

            if "kind" not in data or "id" not in data:
                raise ValueError(
                    "Missing entity information."
                )

            record_id = int(data["id"])

            if record_id <= 0:
                raise ValueError("Invalid entity ID.")

            store.delete_entity(
                data["kind"],
                record_id,
            )

            return self.respond(
                200,
                {"ok": True},
            )

        if path == "/assign":

            required = (
                "vehicle_id",
                "driver_id",
                "route_id",
            )

            if any(key not in data for key in required):
                raise ValueError(
                    "Missing trip assignment information."
                )

            vehicle_id = int(data["vehicle_id"])
            driver_id = int(data["driver_id"])
            route_id = int(data["route_id"])

            if min(vehicle_id, driver_id, route_id) <= 0:
                raise ValueError(
                    "Invalid trip assignment IDs."
                )

            trip_id = store.assign(
                vehicle_id,
                driver_id,
                route_id,
            )

            return self.respond(
                200,
                {"trip_id": trip_id},
            )

        if path == "/end-trip":

            if "trip_id" not in data:
                raise ValueError(
                    "Missing trip ID."
                )

            trip_id = int(data["trip_id"])

            if trip_id <= 0:
                raise ValueError("Invalid trip ID.")

            store.end_trip(trip_id)

            return self.respond(
                200,
                {"ok": True},
            )

        return self.respond(
            404,
            {"error": "Unknown endpoint."},
        )

    def set_preview_selection(self, data):
        """Validate and update the selected phone preview."""

        session_id = data.get("session_id")

        if session_id is not None:

            if not isinstance(session_id, str):
                raise ValueError(
                    "Invalid phone session selection."
                )

            session_id = session_id.strip()

            if not self.server.valid_session_id(session_id):
                raise ValueError(
                    "Invalid phone session selection."
                )

            with self.server.mobile_sessions_lock:
                link = self.server.mobile_sessions.get(
                    session_id
                )

            if link is None:
                raise ValueError(
                    "Selected phone session does not exist."
                )

            if not self.server.store.assignment(link.vehicle):
                session_id = None

        self.server.select_preview(session_id)

        return self.respond(
            200,
            {
                "ok": True,
                "session_id": session_id,
            },
        )
