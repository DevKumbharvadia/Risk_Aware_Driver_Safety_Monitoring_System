
"""Phone GPS speed extraction and shared HTTP request-handler base."""

import math
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler


MAX_SPEED_MPS = 250 / 3.6
MAX_GPS_AGE_SECONDS = 5
MAX_FUTURE_SECONDS = 2
MAX_ACCURACY_METERS = 30
HTTP_SOCKET_TIMEOUT_SECONDS = 5


def _is_finite_number(value):
    """Check for a finite number, excluding booleans."""

    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


class PhoneSpeed:
    """Validate phone GPS fixes and apply fresh speed readings."""

    def __init__(self):
        self.lock = threading.Lock()
        self.sample = None
        self.last_timestamp = -1

    def accept(self, data, now=None):
        """Validate and store a GPS fix received from the phone."""

        now = time.time() if now is None else now

        if not _is_finite_number(now):
            raise ValueError("Invalid current timestamp")

        if not isinstance(data, dict):
            raise ValueError("Expected a GPS object")

        stamp = data.get("timestamp")
        speed = data.get("speed_mps")
        accuracy = data.get("accuracy_m")

        if not _is_finite_number(stamp):
            raise ValueError("Invalid GPS timestamp")

        age = now - stamp

        if not -MAX_FUTURE_SECONDS <= age <= MAX_GPS_AGE_SECONDS:
            raise ValueError(
                "Expired GPS fix or phone/PC clocks disagree"
            )

        if any(
            value is not None and not _is_finite_number(value)
            for value in (speed, accuracy)
        ):
            raise ValueError("Invalid GPS value")

        if speed is not None and not 0 <= speed <= MAX_SPEED_MPS:
            raise ValueError("Speed out of range")

        if accuracy is not None and accuracy < 0:
            raise ValueError("Accuracy out of range")

        received = time.monotonic()

        with self.lock:
            if stamp <= self.last_timestamp:
                raise ValueError("Old or repeated GPS fix")

            self.last_timestamp = stamp
            self.sample = (stamp, received, speed, accuracy)

    def apply(self, readings, now=None, monotonic=None):
        """Apply a fresh, sufficiently accurate GPS speed reading."""

        now = time.time() if now is None else now
        monotonic = time.monotonic() if monotonic is None else monotonic

        if not _is_finite_number(now):
            raise ValueError("Invalid current timestamp")

        if not _is_finite_number(monotonic):
            raise ValueError("Invalid monotonic timestamp")

        required = (
            "motion_source",
            "acceleration",
            "speed",
            "assessment_available",
            "assessment_note",
        )

        if readings is None or not all(
            hasattr(readings, name) for name in required
        ):
            raise ValueError("Invalid sensor readings object")

        readings.motion_source = "phone_gps"
        readings.acceleration = 0
        readings.speed = 0

        with self.lock:
            sample = self.sample

        note = "Waiting for phone GPS"

        if sample is not None:
            stamp, received, speed, accuracy = sample

            timestamp_age = now - stamp
            connection_age = monotonic - received

            timestamp_valid = (
                -MAX_FUTURE_SECONDS
                <= timestamp_age
                <= MAX_GPS_AGE_SECONDS
            )

            connection_valid = (
                0 <= connection_age <= MAX_GPS_AGE_SECONDS
            )

            if not timestamp_valid or not connection_valid:
                note = "Phone GPS stale or disconnected"

            elif accuracy is None or accuracy > MAX_ACCURACY_METERS:
                note = (
                    "Phone GPS position accuracy insufficient "
                    "(limit 30 m)"
                )

            elif speed is None:
                note = "Phone GPS cannot measure speed"

            else:
                readings.speed = round(speed * 3.6, 1)
                readings.assessment_available = True
                readings.assessment_note = ""
                return readings

        readings.assessment_available = False
        readings.assessment_note = note

        return readings


class PhoneHandler(BaseHTTPRequestHandler):
    """HTTP handler with bounded timeouts and safe response handling."""

    def setup(self):
        super().setup()
        self.connection.settimeout(HTTP_SOCKET_TIMEOUT_SECONDS)

    def log_message(self, *args):
        """Avoid logging URLs containing pairing credentials."""
        pass

    def respond(self, code, body, kind="text/plain"):
        """Send a response and return False if the client disconnected."""

        if isinstance(body, str):
            body = body.encode("utf-8")

        if not isinstance(body, bytes):
            raise TypeError("Response body must be bytes or a string")

        try:
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)
            return True

        except (
            BrokenPipeError,
            ConnectionResetError,
            ConnectionAbortedError,
            socket.timeout,
            OSError,
        ):
            return False
