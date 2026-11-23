
"""Independent state and prediction processing for each phone session."""

import math
import re
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


SESSION_ID_PATTERN = re.compile(r"^[a-f0-9]{32}$")


def _positive_vehicle_id(value):
    """Validate and return a positive vehicle ID."""

    if isinstance(value, bool):
        raise ValueError("Invalid vehicle ID.")

    try:
        vehicle_id = int(value)
    except (TypeError, ValueError, OverflowError):
        raise ValueError("Invalid vehicle ID.") from None

    if isinstance(value, float):
        if not math.isfinite(value) or not value.is_integer():
            raise ValueError("Invalid vehicle ID.")

    if isinstance(value, str):
        if str(vehicle_id) != value.strip():
            raise ValueError("Invalid vehicle ID.")

    if vehicle_id <= 0:
        raise ValueError("Invalid vehicle ID.")

    return vehicle_id


def _prediction_timestamp(value):
    """Validate a server-monotonic prediction timestamp."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Invalid prediction timestamp.")

    try:
        timestamp = float(value)
    except (TypeError, ValueError, OverflowError):
        raise ValueError("Invalid prediction timestamp.") from None

    if not math.isfinite(timestamp):
        raise ValueError("Invalid prediction timestamp.")

    return timestamp


class VehicleLink:
    """Authenticated state belonging to one phone session."""

    def __init__(self, vehicle, session_id):
        self.vehicle = _positive_vehicle_id(vehicle)

        if not isinstance(session_id, str):
            raise ValueError("Invalid phone session ID.")

        session_id = session_id.strip()

        if not SESSION_ID_PATTERN.fullmatch(session_id):
            raise ValueError("Invalid phone session ID.")

        self.session_id = session_id

        self.lock = threading.Lock()

        self.engine = RiskEngine()

        self.trip_id = None
        self.previous = 0.0

        self.tracker = PreviewTracker()

        self.overlay = (
            None,
            0.0,
            "UNKNOWN",
        )

        self.created_at = time.time()
        self.last_seen = time.monotonic()

        self.url = ""

    def touch(self):
        """Update the session's last activity time."""

        with self.lock:
            self.last_seen = time.monotonic()

    def receive_prediction(self, fleet, data, stopping_event):
        """Validate, assess and store one browser prediction."""

        with self.lock:

            if stopping_event.is_set():
                raise RuntimeError(
                    "The manager is shutting down."
                )

            if not isinstance(data, dict):
                raise ValueError(
                    "Prediction payload must be a JSON object."
                )

            # Confirm that the vehicle still has an active trip.

            trip = fleet.store.assignment(
                self.vehicle
            )

            if not trip:
                raise ValueError(
                    "Ask the manager to assign this vehicle first."
                )

            # Validate the server-monotonic capture timestamp.

            server_capture = _prediction_timestamp(
                data.get("server_capture")
            )

            now = time.monotonic()

            age = now - server_capture

            if not (
                -PREDICTION_FUTURE_TOLERANCE
                <= age
                <= PREDICTION_MAX_AGE
            ):
                raise ValueError(
                    "Delayed prediction. Reconnecting to the manager…"
                )

            # Decode and validate the browser's calculated measurements.

            readings = prediction_from_payload(data)

            if stopping_event.is_set():
                raise RuntimeError(
                    "The manager is shutting down."
                )

            # Apply the latest vehicle speed information.

            apply_vehicle_speed(
                readings,
                data,
            )

            readings.accelerometer = data.get(
                "accelerometer"
            )

            readings.gyroscope = data.get(
                "gyroscope"
            )

            # Reconstruct Measurements to run its normal validation.

            readings = Measurements.from_dict(
                readings.to_dict()
            )

            if stopping_event.is_set():
                raise RuntimeError(
                    "The manager is shutting down."
                )

            # Calculate the time since the previous prediction.

            gap = (
                now - self.previous
                if self.previous
                else 0.0
            )

            # Reset accumulated risk state when the trip changes or
            # the prediction stream has been interrupted for too long.

            if (
                trip["id"] != self.trip_id
                or gap > 3.0
            ):
                self.engine = RiskEngine()
                gap = 0.0

            gap = max(
                0.0,
                min(2.0, gap),
            )

            self.trip_id = trip["id"]
            self.previous = now

            # Calculate the current fleet risk assessment.

            risk = self.engine.update(
                readings,
                gap,
            )

            # Update the dashboard preview overlay.

            self.overlay = (
                trip["id"],
                time.monotonic(),
                risk.level,
            )

            if stopping_event.is_set():
                raise RuntimeError(
                    "The manager is shutting down."
                )

            # Persist the calculated measurements and risk assessment.

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

            # Return the same response structure expected by the UI.

            return {
                "driver": trip["driver_name"],
                "route": trip["route_name"],

                "mount_note": (
                    "Driver behaviour is classified by the browser ONNX "
                    "model. Drowsiness is independently measured in the "
                    "browser using MediaPipe. Only calculated measurements "
                    "are sent to the manager."
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

                "assessment_note": (
                    readings.assessment_note
                ),

                "inference_ms": readings.inference_ms,

                # Drowsiness measurements from the browser.

                "drowsiness_available": (
                    readings.drowsiness_available
                ),

                "drowsiness_alert_level": (
                    readings.drowsiness_alert_level
                ),

                "eyes_closed": readings.eyes_closed,
                "ear": readings.ear,
                "perclos": readings.perclos,
                "closed_duration": readings.closed_duration,
            }
