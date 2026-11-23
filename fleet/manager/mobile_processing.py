
"""Mobile prediction, GPS and preview processing."""

import math
import time

from ..mobile.phone_speed import PhoneSpeed


# ---------------------------------------------------------------------
# Behaviour labels
# ---------------------------------------------------------------------

BEHAVIOR_LABELS = {
    # New 9-class model
    "safe_driving": "SAFE DRIVING",

    "texting_right": "TEXTING RIGHT",
    "talking_phone_right": "TALKING ON PHONE (RIGHT)",

    "texting_left": "TEXTING LEFT",
    "talking_phone_left": "TALKING ON PHONE (LEFT)",

    "operating_radio": "OPERATING RADIO",
    "drinking": "DRINKING",
    "reaching_behind": "REACHING BEHIND",
    "talking_to_passenger": "TALKING TO PASSENGER",

    # Backward compatibility with previous classifiers
    "texting_phone": "PHONE USE",
    "texting": "PHONE USE",

    "talking_phone": "PHONE USE",
    "talking_on_phone": "PHONE USE",

    "turning": "TURNING",
    "safe": "SAFE DRIVING",

    "other_activities": "OTHER ACTIVITIES",
    "unconfirmed_activity": "UNCONFIRMED ACTIVITY",
    "possible_call": "POSSIBLE CALL",
}


CLASSIFIER_NAMES = {
    # New 9-class model
    "safe_driving": "Safe driving",

    "texting_right": "Texting right",
    "talking_phone_right": "Talking on phone right",

    "texting_left": "Texting left",
    "talking_phone_left": "Talking on phone left",

    "operating_radio": "Operating radio",
    "drinking": "Drinking",
    "reaching_behind": "Reaching behind",
    "talking_to_passenger": "Talking to passenger",

    # Backward compatibility with previous classifiers
    "texting_phone": "Texting on phone",
    "texting": "Texting",

    "talking_phone": "Talking on phone",
    "talking_on_phone": "Talking on phone",

    "turning": "Turning",
    "safe": "Safe driving",

    "other_activities": "Other activities",
    "unconfirmed_activity": "Unconfirmed activity",
    "possible_call": "Possible call",
}


def behavior_label(
    behavior,
    confidence,
    face_activity,
    handset_visible,
):
    """Convert predicted behaviour into a dashboard label."""

    if not isinstance(behavior, str):
        behavior = ""

    behavior = behavior.strip().lower()

    if behavior in BEHAVIOR_LABELS:
        return BEHAVIOR_LABELS[behavior]

    # Preserve the existing phone-detection fallback.
    if handset_visible is True:
        return "PHONE USE"

    return (
        behavior.replace("_", " ").upper()
        if behavior
        else "UNKNOWN"
    )


def classifier_summary(label, score, handset_visible):
    """Format the raw classifier prediction and confidence."""

    if not label:
        return "No prediction"

    label = str(label).strip().lower()

    if not label:
        return "No prediction"

    description = CLASSIFIER_NAMES.get(
        label,
        label.replace("_", " ").title(),
    )

    try:
        score = float(score)

    except (TypeError, ValueError, OverflowError):
        return description

    if not math.isfinite(score):
        return description

    return f"{description} ({score:.1%})"


# ---------------------------------------------------------------------
# Preview processing
# ---------------------------------------------------------------------

class PreviewTracker:
    """Pass through JPEG previews without face detection."""

    def annotate(self, image_bytes, level):
        return image_bytes, None


# ---------------------------------------------------------------------
# GPS processing
# ---------------------------------------------------------------------

def apply_vehicle_speed(readings, data):
    """Apply validated phone GPS data to Measurements."""

    gps = PhoneSpeed()
    fix = {}

    if not isinstance(data, dict):
        data = {}

    gps_data = data.get("gps")

    if gps_data:
        try:
            if not isinstance(gps_data, dict):
                raise ValueError("Invalid GPS object")

            captured = data.get("captured")
            server_capture = data.get("server_capture")
            gps_timestamp = gps_data.get("timestamp")

            timestamps = (
                captured,
                server_capture,
                gps_timestamp,
            )

            if any(
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                for value in timestamps
            ):
                raise ValueError(
                    "Invalid GPS capture timestamp"
                )

            gps_age = captured - gps_timestamp

            if gps_age < -2.0 or gps_age > 30.0:
                raise ValueError(
                    "GPS reading is outside the accepted time window"
                )

            adjusted_timestamp = (
                time.time()
                - gps_age
                - max(
                    0.0,
                    time.monotonic() - server_capture,
                )
            )

            validated_fix = {
                **gps_data,
                "timestamp": adjusted_timestamp,
            }

            gps.accept(validated_fix)

            fix = validated_fix

        except (
            ValueError,
            KeyError,
            TypeError,
            OverflowError,
        ):
            fix = {}

    # Apply GPS information to vehicle measurements.
    gps.apply(readings)

    # Determine whether usable GPS speed is available.
    assessment_note = getattr(
        readings,
        "assessment_note",
        "",
    )

    if not isinstance(assessment_note, str):
        assessment_note = ""

    missing = assessment_note.startswith(
        (
            "Phone GPS",
            "Waiting for phone GPS",
        )
    )

    readings.speed_method = (
        "unavailable"
        if missing
        else "GPS estimate"
        if fix.get("estimated")
        else "GPS"
    )

    # Provide useful messages when GPS is unavailable.
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
            assessment_note,
        )
