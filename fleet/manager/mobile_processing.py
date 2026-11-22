
"""Mobile prediction, GPS and preview processing."""

import math
import time

from ..mobile.phone_speed import PhoneSpeed


def behavior_label(
    behavior,
    confidence,
    face_activity,
    handset_visible,
):
    """Convert predicted behaviour into a dashboard label."""

    behavior = behavior.strip().lower() if isinstance(behavior, str) else ""

    labels = {
        "texting_phone": "PHONE USE",
        "talking_phone": "PHONE USE",
        "turning": "TURNING",
        "safe_driving": "SAFE DRIVING",
        "other_activities": "OTHER ACTIVITIES",
        "unconfirmed_activity": "UNCONFIRMED ACTIVITY",
        "possible_call": "POSSIBLE CALL",
    }

    if behavior in labels:
        return labels[behavior]

    if handset_visible is True:
        return "PHONE USE"

    return behavior.replace("_", " ").upper() if behavior else "UNKNOWN"


def classifier_summary(label, score, handset_visible):
    """Format the raw classifier prediction and confidence."""

    if not label:
        return "No prediction"

    label = str(label).strip().lower()

    names = {
        "texting_phone": "Texting on phone",
        "talking_phone": "Talking on phone",
        "turning": "Turning",
        "safe_driving": "Safe driving",
        "other_activities": "Other activities",
    }

    description = names.get(label, label.replace("_", " ").title())

    try:
        score = float(score)
    except (TypeError, ValueError):
        return description

    if not math.isfinite(score):
        return description

    return f"{description} ({score:.1%})"


class PreviewTracker:
    """Pass through JPEG previews without face detection."""

    def annotate(self, image_bytes, level):
        return image_bytes, None


def apply_vehicle_speed(readings, data):
    """Apply validated phone GPS data to Measurements."""

    gps = PhoneSpeed()
    fix = {}

    if data.get("gps"):
        try:
            fix = data["gps"]

            if not isinstance(fix, dict):
                raise ValueError("Invalid GPS object")

            captured = data.get("captured")
            server_capture = data.get("server_capture")
            gps_timestamp = fix.get("timestamp")

            timestamps = (captured, server_capture, gps_timestamp)

            if any(
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not math.isfinite(value)
                for value in timestamps
            ):
                raise ValueError("Invalid GPS capture timestamp")

            gps_age = captured - gps_timestamp
            adjusted_timestamp = (
                time.time()
                - gps_age
                - max(0.0, time.monotonic() - server_capture)
            )

            gps.accept({
                **fix,
                "timestamp": adjusted_timestamp,
            })

        except (ValueError, KeyError, TypeError, OverflowError):
            fix = {}

    gps.apply(readings)

    missing = readings.assessment_note.startswith(
        ("Phone GPS", "Waiting for phone GPS")
    )

    readings.speed_method = (
        "unavailable"
        if missing
        else "GPS estimate" if fix.get("estimated") else "GPS"
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
