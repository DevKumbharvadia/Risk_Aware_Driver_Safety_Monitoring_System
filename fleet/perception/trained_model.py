
"""Validation and conversion of browser-side ONNX predictions.

The neural network runs on the smartphone browser.
The server only validates its prediction and constructs Measurements.
"""

import math

from ..risk.engine import Measurements


CLASS_NAMES = (
    "other_activities",
    "safe_driving",
    "talking_phone",
    "texting_phone",
    "turning",
)

DEFAULT_THRESHOLD = 0.65


def unavailable_readings(note):
    """Create Measurements when a prediction cannot be obtained."""
    return Measurements(
        source="trained_model",
        face_visible=None,
        assessment_available=False,
        assessment_note=note,
    )


def prediction_to_readings(
    label,
    confidence,
    inference_ms=0.0,
    threshold=DEFAULT_THRESHOLD,
):
    """Convert one validated browser prediction into Measurements."""

    if not isinstance(label, str) or label not in CLASS_NAMES:
        raise ValueError("Unknown behaviour class.")

    if (
        isinstance(confidence, bool)
        or not isinstance(confidence, (int, float))
    ):
        raise ValueError("Invalid confidence.")

    if not math.isfinite(confidence) or not 0 <= confidence <= 1:
        raise ValueError("Confidence must be between zero and one.")

    if (
        isinstance(inference_ms, bool)
        or not isinstance(inference_ms, (int, float))
    ):
        raise ValueError("Invalid inference duration.")

    if not math.isfinite(inference_ms) or not 0 <= inference_ms <= 600000:
        raise ValueError("Invalid inference duration.")

    if (
        isinstance(threshold, bool)
        or not isinstance(threshold, (int, float))
        or not math.isfinite(threshold)
        or not 0 < threshold <= 1
    ):
        raise ValueError("Invalid decision threshold.")

    confidence = float(confidence)
    inference_ms = float(inference_ms)
    threshold = float(threshold)

    readings = Measurements(
        source="trained_model",
        face_visible=None,
        behavior=label,
        confidence=confidence,
        inference_ms=inference_ms,
        classifier_label=label,
        classifier_score=confidence,
        handset_visible=None,
    )

    if confidence < threshold:
        readings.assessment_available = False
        readings.assessment_note = (
            "Class score below decision threshold; behaviour uncertain"
        )

    elif label == "other_activities":
        readings.assessment_available = False
        readings.assessment_note = (
            "Other activities predicted; specific hazard cannot be determined"
        )

    elif label in ("talking_phone", "texting_phone"):
        # These are model-predicted behaviours, not independently
        # confirmed handset detections.
        readings.phone_use = True
        readings.assessment_note = (
            "Phone-use behaviour predicted by the browser model; "
            "not independently handset-confirmed"
        )

    elif label == "turning":
        readings.assessment_note = (
            "Turning behaviour predicted by the browser model"
        )

    return readings


def prediction_from_payload(data, threshold=DEFAULT_THRESHOLD):
    """Validate the JSON prediction received from the mobile browser."""

    if not isinstance(data, dict):
        raise ValueError("Prediction payload must be an object.")

    label = data.get("behavior")
    confidence = data.get("confidence")
    inference_ms = data.get("inference_ms", 0.0)

    return prediction_to_readings(
        label=label,
        confidence=confidence,
        inference_ms=inference_ms,
        threshold=threshold,
    )
