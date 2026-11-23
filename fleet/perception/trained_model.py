
"""Validate browser ONNX predictions and drowsiness measurements."""

import math

from ..risk.engine import Measurements


CLASS_NAMES = (
    "other_activities",
    "safe_driving",
    "talking_phone",
    "texting_phone",
    "turning",
)

DEFAULT_THRESHOLD = 0.45
PHONE_USE_THRESHOLD = 0.25

PHONE_CLASSES = ("talking_phone", "texting_phone")

ALERT_LEVELS = ("NORMAL", "WARNING", "CRITICAL", "UNKNOWN")

BEHAVIOR_NOTES = {
    "texting_phone": (
        "Texting behaviour predicted by the browser classifier; "
        "physical handset presence is not independently confirmed"
    ),
    "talking_phone": (
        "Talking on phone predicted by the browser classifier; "
        "physical handset presence is not independently confirmed"
    ),
    "turning": "Turning behaviour predicted by the browser classifier",
    "other_activities": (
        "Other activities predicted; no specific hazard identified"
    ),
    "safe_driving": "Safe-driving behaviour predicted",
}


def _valid_number(value):
    """Check for finite numeric values, excluding booleans."""
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _optional_ratio(data, name):
    """Validate an optional measurement between zero and one."""
    value = data.get(name)

    if value is None:
        return None

    if not _valid_number(value) or not 0 <= value <= 1:
        raise ValueError(f"Invalid {name} measurement.")

    return float(value)


def unavailable_readings(note):
    """Create Measurements when no usable prediction is available."""
    return Measurements(
        source="trained_model",
        face_visible=None,
        assessment_available=False,
        assessment_note=str(note)[:250],
    )


def prediction_to_readings(
    label,
    confidence,
    inference_ms=0.0,
    threshold=None,
):
    """Convert a validated ONNX prediction into Measurements."""

    if not isinstance(label, str) or label not in CLASS_NAMES:
        raise ValueError(
            f"Unknown behaviour class: {label!r}. "
            f"Expected one of {CLASS_NAMES}."
        )

    if not _valid_number(confidence) or not 0 <= confidence <= 1:
        raise ValueError("Confidence must be between zero and one.")

    if not _valid_number(inference_ms) or not 0 <= inference_ms <= 600000:
        raise ValueError("Invalid inference duration.")

    if threshold is None:
        threshold = (
            PHONE_USE_THRESHOLD
            if label in PHONE_CLASSES
            else DEFAULT_THRESHOLD
        )

    if not _valid_number(threshold) or not 0 < threshold <= 1:
        raise ValueError(
            "Threshold must be greater than zero and at most one."
        )

    confidence = float(confidence)
    inference_ms = float(inference_ms)
    threshold = float(threshold)

    accepted = confidence >= threshold

    readings = Measurements(
        source="trained_model",
        face_visible=None,
        assessment_available=True,
        behavior=label if accepted else "unconfirmed_activity",
        confidence=confidence,
        inference_ms=inference_ms,
        classifier_label=label,
        classifier_score=confidence,
        handset_visible=None,
        phone_use=accepted and label in PHONE_CLASSES,
    )

    if not accepted:
        readings.assessment_note = (
            f"Prediction below confidence threshold "
            f"({confidence:.3f} < {threshold:.3f}); "
            "behaviour is unconfirmed"
        )
    else:
        readings.assessment_note = BEHAVIOR_NOTES[label]

    return readings


def prediction_from_payload(data, threshold=None):
    """Validate ONNX and independent browser drowsiness measurements."""

    if not isinstance(data, dict):
        raise ValueError("Prediction payload must be an object.")

    # ---------------------------------------------------------
    # Behaviour classifier prediction
    # ---------------------------------------------------------

    label = data.get("classifier_label")
    confidence = data.get("classifier_score")

    if not isinstance(label, str) or label not in CLASS_NAMES:
        label = data.get("behavior")
        confidence = data.get("confidence")

        if not isinstance(label, str) or label not in CLASS_NAMES:
            raise ValueError(
                "Prediction payload has no valid behavior/classifier_label."
            )

    elif not _valid_number(confidence):
        confidence = data.get("confidence")

    if not _valid_number(confidence):
        raise ValueError("Prediction payload has no valid confidence.")

    inference_ms = data.get("inference_ms", 0.0)

    if not _valid_number(inference_ms):
        raise ValueError("Invalid inference_ms.")

    readings = prediction_to_readings(
        label,
        confidence,
        inference_ms,
        threshold,
    )

    # ---------------------------------------------------------
    # Browser MediaPipe availability and face detection
    # ---------------------------------------------------------

    available = data.get("drowsiness_available", False)
    face_detected = data.get("face_detected", False)
    eyes_closed = data.get("eyes_closed", False)

    if type(available) is not bool:
        raise ValueError("Invalid drowsiness availability.")

    if type(face_detected) is not bool:
        raise ValueError("Invalid face detection measurement.")

    if type(eyes_closed) is not bool:
        raise ValueError("Invalid eye-closure measurement.")

    if face_detected and not available:
        raise ValueError(
            "A face cannot be detected when drowsiness detection is unavailable."
        )

    # ---------------------------------------------------------
    # Eye measurements
    # ---------------------------------------------------------

    ear = _optional_ratio(data, "ear")
    left_ear = _optional_ratio(data, "left_ear")
    right_ear = _optional_ratio(data, "right_ear")
    perclos = _optional_ratio(data, "perclos")

    closed_duration = data.get("closed_duration", 0.0)

    if (
        not _valid_number(closed_duration)
        or not 0 <= closed_duration <= 600
    ):
        raise ValueError("Invalid eye-closure duration.")

    closed_duration = float(closed_duration)

    # ---------------------------------------------------------
    # Alert validation
    # ---------------------------------------------------------

    alert_level = data.get(
        "drowsiness_alert_level",
        "UNKNOWN",
    )

    if not isinstance(alert_level, str) or alert_level not in ALERT_LEVELS:
        raise ValueError("Invalid drowsiness alert level.")

    # ---------------------------------------------------------
    # Normalize missing or unavailable facial measurements
    # ---------------------------------------------------------

    if not available:
        if eyes_closed:
            raise ValueError(
                "Eye closure cannot be true when drowsiness is unavailable."
            )

        face_detected = False
        alert_level = "UNKNOWN"
        ear = None
        left_ear = None
        right_ear = None
        perclos = None
        closed_duration = 0.0

    elif not face_detected:
        # The detector is running, but no face is visible.
        # This must not be interpreted as normal alertness.

        if eyes_closed:
            raise ValueError(
                "Eye closure cannot be true when no face is detected."
            )

        alert_level = "UNKNOWN"
        ear = None
        left_ear = None
        right_ear = None
        closed_duration = 0.0

    # ---------------------------------------------------------
    # Store drowsiness measurements
    # ---------------------------------------------------------

    readings.drowsiness_available = available
    readings.face_detected = face_detected
    readings.eyes_closed = eyes_closed if face_detected else False

    readings.drowsiness_alert_level = alert_level

    readings.ear = ear
    readings.left_ear = left_ear
    readings.right_ear = right_ear

    readings.perclos = perclos
    readings.closed_duration = closed_duration

    return readings
