
"""Phone GPS speed extraction and the shared HTTPS request-handler base."""

import math
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler


MAX_SPEED_MPS = 250 / 3.6
MAX_GPS_AGE_SECONDS = 5
MAX_FUTURE_SECONDS = 2
MAX_ACCURACY_METERS = 30


def _is_finite_number(value):
    """Return True for finite integers or floats, excluding booleans."""
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
            raise ValueError("Expected an object")

        stamp = data.get("timestamp")
        speed = data.get("speed_mps")
        accuracy = data.get("accuracy_m")

        if not _is_finite_number(stamp):
            raise ValueError("Invalid timestamp")

        if not -MAX_FUTURE_SECONDS <= now - stamp <= MAX_GPS_AGE_SECONDS:
            raise ValueError("Expired GPS fix or phone/PC clocks disagree")

        for value in (speed, accuracy):
            if value is not None and not _is_finite_number(value):
                raise ValueError("Invalid GPS value")

        if speed is not None and not 0 <= speed <= MAX_SPEED_MPS:
            raise ValueError("Speed out of range")

        if accuracy is not None and accuracy < 0:
            raise ValueError("Accuracy out of range")

        with self.lock:
            if stamp <= self.last_timestamp:
                raise ValueError("Old or repeated GPS fix")

            self.last_timestamp = stamp
            self.sample = (
                stamp,
                time.monotonic(),
                speed,
                accuracy,
            )

    def apply(self, readings, now=None, monotonic=None):
        """Apply a fresh, sufficiently accurate phone GPS speed reading."""
        now = time.time() if now is None else now
        monotonic = time.monotonic() if monotonic is None else monotonic

        readings.motion_source = "phone_gps"
        readings.acceleration = 0
        readings.speed = 0

        with self.lock:
            sample = self.sample

        note = "Waiting for phone GPS"

        if sample is not None:
            stamp, received, speed, accuracy = sample

            timestamp_valid = (
                _is_finite_number(now)
                and -MAX_FUTURE_SECONDS
                <= now - stamp
                <= MAX_GPS_AGE_SECONDS
            )

            connection_valid = (
                _is_finite_number(monotonic)
                and monotonic - received <= MAX_GPS_AGE_SECONDS
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
                return readings

        readings.assessment_available = False
        readings.assessment_note = note

        return readings


class PhoneHandler(BaseHTTPRequestHandler):
    """Base handler with bounded reads and safe disconnected-client handling."""

    def setup(self):
        super().setup()
        self.connection.settimeout(5)

    def log_message(self, *args):
        # Pairing credentials must not appear in request logs.
        pass

    def respond(self, code, body, kind="text/plain"):
        """Send an HTTP response safely.

        Returns False if the client has disconnected.
        """
        try:
            if isinstance(body, str):
                body = body.encode("utf-8")

            if not isinstance(body, bytes):
                raise TypeError("Response body must be bytes or a string")

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
            # The client may disconnect while the response is being sent.
            return False
