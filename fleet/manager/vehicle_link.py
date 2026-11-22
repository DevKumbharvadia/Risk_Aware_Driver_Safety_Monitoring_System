
"""Independent state and prediction processing for each phone session."""

import math
import threading
import time
import uuid

from ..perception.trained_model import prediction_from_payload
from ..risk.engine import Measurements, RiskEngine
from .mobile_config import (
    PREDICTION_MAX_AGE,
    PREDICTION_FUTURE_TOLERANCE,
)
from .mobile_processing import (
    PreviewTracker,
    apply_vehicle_speed,
    behavior_label,
    classifier_summary,
)
from .storage import utc_now


class VehicleLink:
    """Authenticated state belonging to one phone session."""

    def __init__(self, vehicle, session_id):
        self.vehicle = int(vehicle)
        self.session_id = str(session_id)

        self.lock = threading.Lock()
        self.engine = RiskEngine()
        self.trip_id = None
        self.previous = 0.0

        self.tracker = PreviewTracker()
        self.overlay = (None, 0.0, "UNKNOWN")

        self.created_at = time.time()
        self.last_seen = time.monotonic()
        self.url = ""

    def touch(self):
        """Update the session's last activity time."""

        self.last_seen = time.monotonic()

    def receive_prediction(self, fleet, data, stopping_event):
        """Validate, assess and store one browser prediction."""

        with self.lock:
            if stopping_event.is_set():
                raise RuntimeError("The manager is shutting down.")

            if not isinstance(data, dict):
                raise ValueError("Prediction payload must be a JSON object.")

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
                raise ValueError("Invalid prediction timestamp.")

            age = now - server_capture

            if not -PREDICTION_FUTURE_TOLERANCE <= age <= PREDICTION_MAX_AGE:
                raise ValueError(
                    "Delayed prediction. Reconnecting to the manager…"
                )

            readings = prediction_from_payload(data)

            if stopping_event.is_set():
                raise RuntimeError("The manager is shutting down.")

            apply_vehicle_speed(readings, data)

            readings.accelerometer = data.get("accelerometer")
            readings.gyroscope = data.get("gyroscope")
            readings = Measurements.from_dict(readings.to_dict())

            if stopping_event.is_set():
                raise RuntimeError("The manager is shutting down.")

            gap = now - self.previous if self.previous else 0.0

            if trip["id"] != self.trip_id or gap > 3.0:
                self.engine = RiskEngine()
                gap = 0.0

            gap = max(0.0, min(2.0, gap))
            self.trip_id = trip["id"]
            self.previous = now

            risk = self.engine.update(readings, gap)

            self.overlay = (trip["id"], time.monotonic(), risk.level)

            fleet.store.add_sample({
                "id": str(uuid.uuid4()),
                "vehicle_id": self.vehicle,
                "trip_id": trip["id"],
                "captured_at": utc_now(),
                "readings": readings.to_dict(),
                "risk": risk.to_dict(),
            })

            if stopping_event.is_set():
                raise RuntimeError("The manager is shutting down.")

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
                "assessment_available": readings.assessment_available,
                "assessment_note": readings.assessment_note,
                "inference_ms": readings.inference_ms,
            }
