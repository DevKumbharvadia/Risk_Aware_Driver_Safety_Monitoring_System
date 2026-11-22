"""Phone GPS speed extraction and the shared HTTPS request-handler base."""
import math
import threading
import time
from http.server import BaseHTTPRequestHandler


class PhoneSpeed:
    def __init__(self):
        self.lock = threading.Lock()
        self.sample = None
        self.last_timestamp = -1

    def accept(self, data, now=None):
        now = time.time() if now is None else now
        if not isinstance(data, dict):
            raise ValueError("Expected an object")
        stamp, speed, accuracy = (data.get(key) for key in ("timestamp", "speed_mps", "accuracy_m"))
        if isinstance(stamp, bool) or not isinstance(stamp, (int, float)) or not math.isfinite(stamp):
            raise ValueError("Invalid timestamp")
        if not -2 <= now - stamp <= 5:
            raise ValueError("Expired GPS fix or phone/PC clocks disagree")
        for value in (speed, accuracy):
            if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)):
                raise ValueError("Invalid GPS value")
        if speed is not None and not 0 <= speed <= 250 / 3.6:
            raise ValueError("Speed out of range")
        if accuracy is not None and accuracy < 0:
            raise ValueError("Accuracy out of range")
        with self.lock:
            if stamp <= self.last_timestamp:
                raise ValueError("Old or repeated GPS fix")
            self.last_timestamp = stamp
            self.sample = (stamp, time.monotonic(), speed, accuracy)

    def apply(self, readings, now=None, monotonic=None):
        now = time.time() if now is None else now
        monotonic = time.monotonic() if monotonic is None else monotonic
        readings.motion_source = "phone_gps"
        readings.acceleration = 0  # Not measured; never infer harsh braking from GPS jitter.
        readings.speed = 0  # Placeholder only; unavailable assessment prevents stopped logic.
        with self.lock:
            sample = self.sample
        note = "Waiting for phone GPS"
        if sample:
            stamp, received, speed, accuracy = sample
            if not -2 <= now - stamp <= 5 or monotonic - received > 5:
                note = "Phone GPS stale or disconnected"
            elif accuracy is None or accuracy > 30:
                note = "Phone GPS position accuracy insufficient (limit 30 m)"
            elif speed is None:
                note = "Phone GPS cannot measure speed"
            else:
                readings.speed = round(speed * 3.6, 1)
                return readings
        readings.assessment_available = False
        readings.assessment_note = note
        return readings


class PhoneHandler(BaseHTTPRequestHandler):
    """Base handler: connection timeout, silent request logging and a JSON/raw responder."""

    def setup(self):
        super().setup()
        self.connection.settimeout(5)

    def log_message(self, *args):
        pass  # Pairing credentials must not appear in request logs.

    def respond(self, code, body, kind="text/plain"):
        self.send_response(code)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(body)
