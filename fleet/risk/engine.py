
"""Explainable temporal rules for driver risk assessment."""

import math
from collections import deque
from dataclasses import asdict, dataclass

from .attention import AttentionPolicy, SpeedContext


# =========================================================
# NINE-CLASS ONNX CLASSIFIER
# =========================================================

CLASSIFIER_LABELS = (
    "safe_driving",
    "texting_right",
    "talking_phone_right",
    "texting_left",
    "talking_phone_left",
    "operating_radio",
    "drinking",
    "reaching_behind",
    "talking_to_passenger",
)

# Preserve compatibility with existing simulation and legacy
# behaviour values while accepting the new model labels.

BEHAVIOUR_LABELS = (
    "",
    *CLASSIFIER_LABELS,
    "unconfirmed_activity",
    "possible_call",
    "texting_phone",
    "talking_phone",
    "turning",
    "other_activities",
)

MEASUREMENT_SOURCES = ("simulation", "trained_model")
MOTION_SOURCES = ("simulation", "phone_gps")
SPEED_METHODS = ("", "GPS", "GPS estimate", "unavailable")

PHONE_USE_RELEASE_GRACE = 0.75


# =========================================================
# BEHAVIOUR GROUPS
# =========================================================

TEXTING_BEHAVIOURS = (
    "texting_right",
    "texting_left",
    "texting_phone",
)

PHONE_CALL_BEHAVIOURS = (
    "talking_phone_right",
    "talking_phone_left",
    "talking_phone",
    "possible_call",
)

RADIO_BEHAVIOURS = (
    "operating_radio",
)

DRINKING_BEHAVIOURS = (
    "drinking",
)

REACHING_BEHAVIOURS = (
    "reaching_behind",
)

PASSENGER_BEHAVIOURS = (
    "talking_to_passenger",
)

TURNING_BEHAVIOURS = (
    "turning",
)


# =========================================================
# VALIDATION
# =========================================================

def _finite_number(value):
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


@dataclass
class Measurements:
    eyes_closed: bool = False
    yawning: bool = False
    looking_away: bool = False
    phone_use: bool = False

    drowsiness_available: bool = False
    face_detected: bool = False
    drowsiness_alert_level: str = "UNKNOWN"

    ear: float | None = None
    left_ear: float | None = None
    right_ear: float | None = None
    perclos: float | None = None
    closed_duration: float = 0.0

    face_visible: bool | None = True
    face_activity: str = ""

    speed: float = 0.0
    acceleration: float = 0.0

    source: str = "simulation"
    motion_source: str = "simulation"
    speed_method: str = ""

    behavior: str = ""
    confidence: float = 0.0
    inference_ms: float = 0.0

    assessment_available: bool = True
    assessment_note: str = ""

    accelerometer: list | None = None
    gyroscope: list | None = None

    handset_visible: bool | None = None
    classifier_label: str = ""
    classifier_score: float = 0.0

    @classmethod
    def from_dict(cls, values):
        """Validate a dictionary and create Measurements."""

        if not isinstance(values, dict):
            raise ValueError("Measurements must be an object.")

        result = cls()

        boolean_fields = (
            "eyes_closed",
            "yawning",
            "looking_away",
            "phone_use",
            "assessment_available",
            "drowsiness_available",
            "face_detected",
        )

        for name in boolean_fields:
            value = values.get(name, getattr(result, name))

            if type(value) is not bool:
                raise ValueError(
                    f"{name} must be true or false."
                )

            setattr(result, name, value)

        result.source = values.get(
            "source",
            "simulation",
        )

        if result.source not in MEASUREMENT_SOURCES:
            raise ValueError("Unknown measurement source.")

        face = values.get("face_visible", True)

        if type(face) is not bool and not (
            face is None and result.source == "trained_model"
        ):
            raise ValueError(
                "Face visibility must be boolean, or unmeasured "
                "for the classifier."
            )

        result.face_visible = face

        handset = values.get("handset_visible")

        if handset is not None and type(handset) is not bool:
            raise ValueError(
                "Handset visibility must be boolean or unmeasured."
            )

        result.handset_visible = handset

        result.classifier_label = values.get(
            "classifier_label",
            "",
        )

        if (
            not isinstance(result.classifier_label, str)
            or result.classifier_label not in ("",) + CLASSIFIER_LABELS
        ):
            raise ValueError("Unknown raw classifier label.")

        for name in ("accelerometer", "gyroscope"):

            vector = values.get(name)

            if vector is not None:

                if (
                    not isinstance(vector, list)
                    or len(vector) != 3
                    or any(not _finite_number(v) for v in vector)
                ):
                    raise ValueError(
                        f"Invalid {name} vector."
                    )

                vector = [float(v) for v in vector]

            setattr(result, name, vector)

        numeric_fields = {
            "speed": (0, 250),
            "acceleration": (-20, 20),
            "confidence": (0, 1),
            "classifier_score": (0, 1),
            "inference_ms": (0, 600000),
            "closed_duration": (0, 600),
        }

        for name, (minimum, maximum) in numeric_fields.items():

            value = values.get(
                name,
                getattr(result, name),
            )

            if (
                not _finite_number(value)
                or not minimum <= value <= maximum
            ):
                raise ValueError(
                    f"{name} must be between {minimum} and {maximum}."
                )

            setattr(result, name, float(value))

        for name in ("ear", "left_ear", "right_ear", "perclos"):

            value = values.get(name)

            if value is not None:

                if (
                    not _finite_number(value)
                    or not 0 <= value <= 1
                ):
                    raise ValueError(
                        f"Invalid {name} measurement."
                    )

                value = float(value)

            setattr(result, name, value)

        result.drowsiness_alert_level = values.get(
            "drowsiness_alert_level",
            "UNKNOWN",
        )

        if result.drowsiness_alert_level not in (
            "NORMAL",
            "WARNING",
            "CRITICAL",
            "UNKNOWN",
        ):
            raise ValueError(
                "Invalid drowsiness alert level."
            )

        if not result.drowsiness_available:

            if result.eyes_closed:
                raise ValueError(
                    "Eye closure cannot be used without drowsiness measurements."
                )

            if result.face_detected:
                raise ValueError(
                    "A face cannot be detected when drowsiness is unavailable."
                )

            if result.drowsiness_alert_level != "UNKNOWN":
                raise ValueError(
                    "Unavailable drowsiness must have UNKNOWN alert level."
                )

            result.ear = None
            result.left_ear = None
            result.right_ear = None
            result.perclos = None
            result.closed_duration = 0.0

        elif not result.face_detected:

            if result.eyes_closed:
                raise ValueError(
                    "Eye closure cannot be true when no face is detected."
                )

            if result.drowsiness_alert_level != "UNKNOWN":
                raise ValueError(
                    "Missing face must have UNKNOWN alert level."
                )

            result.ear = None
            result.left_ear = None
            result.right_ear = None
            result.closed_duration = 0.0

        elif result.drowsiness_alert_level == "UNKNOWN":

            raise ValueError(
                "Detected face measurements need a valid alert level."
            )

        result.motion_source = values.get(
            "motion_source",
            "simulation",
        )

        if result.motion_source not in MOTION_SOURCES:
            raise ValueError("Unknown motion source.")

        result.speed_method = values.get(
            "speed_method",
            "",
        )

        if result.speed_method not in SPEED_METHODS:
            raise ValueError(
                "Unknown speed measurement method."
            )

        if (
            result.motion_source == "phone_gps"
            and result.acceleration != 0
        ):
            raise ValueError(
                "Phone GPS does not measure acceleration in this version."
            )

        result.behavior = values.get(
            "behavior",
            "",
        )

        if (
            not isinstance(result.behavior, str)
            or result.behavior not in BEHAVIOUR_LABELS
        ):
            raise ValueError(
                "Unknown behavior class."
            )

        note = values.get(
            "assessment_note",
            "",
        )

        if not isinstance(note, str) or len(note) > 250:
            raise ValueError("Invalid assessment note.")

        result.assessment_note = note

        result.face_activity = values.get(
            "face_activity",
            "",
        )

        if result.face_activity not in (
            "",
            "Eyes closed",
            "Looking aside",
            "Facing forward",
        ):
            raise ValueError("Invalid face activity.")

        # The ONNX behaviour classifier does not measure face visibility.
        if result.source == "trained_model" and (
            result.face_visible is not None
            or result.face_activity
        ):
            raise ValueError(
                "The ONNX classifier does not measure face visibility "
                "or face activity."
            )

        return result

    def to_dict(self):
        """Convert all measurements to a serializable dictionary."""
        return asdict(self)


# =========================================================
# RISK RESULT
# =========================================================

@dataclass
class RiskResult:
    score: int
    level: str
    reason: str

    def to_dict(self):
        return asdict(self)


# =========================================================
# RISK ENGINE
# =========================================================

class RiskEngine:
    """Accumulate behaviour duration and require recovery before clearing risk."""

    DURATION_FIELDS = (
        "eyes_closed",
        "yawning",
        "looking_away",
        "phone_use",
        "turning",
        "texting",
        "phone_call",
        "radio",
        "drinking",
        "reaching_behind",
        "passenger_talk",
    )

    # Temporal rules:
    # (duration field, threshold seconds, risk points, explanation)

    RULES = (
        ("phone_use", 2, 65, "Sustained phone use"),
        ("texting", 1.5, 75, "Sustained texting while driving"),
        ("phone_call", 2, 60, "Sustained phone conversation"),
        ("drinking", 2, 60, "Drinking while driving"),
        ("reaching_behind", 1.5, 65, "Reaching behind while driving"),
        ("radio", 3, 25, "Operating vehicle radio"),
        ("passenger_talk", 4, 15, "Sustained passenger conversation"),
        ("yawning", 2, 25, "Sustained yawning"),
    )

    LEVEL_RANKS = {
        "UNKNOWN": -1,
        "LOW": 0,
        "CAUTION": 1,
        "HIGH": 2,
    }

    def __init__(self, attention_policy=None):

        self.attention_policy = (
            attention_policy or AttentionPolicy()
        )

        self.speed_context = SpeedContext(
            self.attention_policy
        )

        self.durations = dict.fromkeys(
            self.DURATION_FIELDS,
            0.0,
        )

        self.phone_use_gap = 0.0

        self.source = None

        self.previous = RiskResult(
            0,
            "LOW",
            "No sustained risky behavior",
        )

        self.recovery = 0.0
        self.observed_time = 0.0

        self.yawn_starts = deque()
        self.was_yawning = False

    # -----------------------------------------------------
    # VALIDATE MEASUREMENTS
    # -----------------------------------------------------

    @staticmethod
    def _validate_readings(readings):

        if not isinstance(readings, Measurements):
            raise TypeError(
                "readings must be a Measurements instance."
            )

        for name, minimum, maximum in (
            ("speed", 0, 250),
            ("acceleration", -20, 20),
            ("closed_duration", 0, 600),
        ):

            value = getattr(readings, name)

            if (
                not _finite_number(value)
                or not minimum <= value <= maximum
            ):
                raise ValueError(
                    f"Invalid measurement: {name}."
                )

        for name in (
            "eyes_closed",
            "yawning",
            "looking_away",
            "phone_use",
            "assessment_available",
            "drowsiness_available",
            "face_detected",
        ):

            if type(getattr(readings, name)) is not bool:
                raise ValueError(
                    f"{name} must be true or false."
                )

        for name in ("ear", "left_ear", "right_ear", "perclos"):

            value = getattr(readings, name)

            if value is not None and (
                not _finite_number(value)
                or not 0 <= value <= 1
            ):
                raise ValueError(
                    f"Invalid measurement: {name}."
                )

        if readings.drowsiness_alert_level not in (
            "NORMAL",
            "WARNING",
            "CRITICAL",
            "UNKNOWN",
        ):
            raise ValueError(
                "Invalid drowsiness alert level."
            )

        if not readings.drowsiness_available:

            if readings.eyes_closed or readings.face_detected:
                raise ValueError(
                    "Facial measurements cannot be used when drowsiness is unavailable."
                )

            if readings.drowsiness_alert_level != "UNKNOWN":
                raise ValueError(
                    "Unavailable drowsiness must have UNKNOWN alert level."
                )

        elif not readings.face_detected:

            if readings.eyes_closed:
                raise ValueError(
                    "Eye closure cannot be true when no face is detected."
                )

            if readings.drowsiness_alert_level != "UNKNOWN":
                raise ValueError(
                    "Missing face must have UNKNOWN alert level."
                )

        elif readings.drowsiness_alert_level == "UNKNOWN":

            raise ValueError(
                "Detected face measurements need a valid alert level."
            )

        if readings.source not in MEASUREMENT_SOURCES:
            raise ValueError("Unknown measurement source.")

        if readings.motion_source not in MOTION_SOURCES:
            raise ValueError("Unknown motion source.")

        if readings.speed_method not in SPEED_METHODS:
            raise ValueError("Unknown speed measurement method.")

        if readings.behavior not in BEHAVIOUR_LABELS:
            raise ValueError("Unknown behavior class.")

        if readings.classifier_label not in ("",) + CLASSIFIER_LABELS:
            raise ValueError("Unknown raw classifier label.")

    # -----------------------------------------------------
    # TEMPORAL BEHAVIOUR TRACKING
    # -----------------------------------------------------

    def _update_durations(self, readings, elapsed):

        behavior = readings.behavior

        for name in self.DURATION_FIELDS:

            if name == "eyes_closed":

                active = (
                    readings.drowsiness_available
                    and readings.face_detected
                    and readings.eyes_closed
                )

                # Preserve legacy simulation eye-closure support.
                if readings.source == "simulation":
                    active = readings.eyes_closed

                self.durations[name] = (
                    self.durations[name] + elapsed
                    if active else 0.0
                )

                continue

            if name == "phone_use":

                if readings.phone_use:

                    self.durations[name] += elapsed
                    self.phone_use_gap = 0.0

                elif self.durations[name] > 0:

                    self.phone_use_gap += elapsed

                    if (
                        self.phone_use_gap
                        <= PHONE_USE_RELEASE_GRACE
                    ):
                        self.durations[name] += elapsed

                    else:
                        self.durations[name] = 0.0
                        self.phone_use_gap = 0.0

                continue

            behavior_groups = {

                "texting": TEXTING_BEHAVIOURS,

                "phone_call": PHONE_CALL_BEHAVIOURS,

                "radio": RADIO_BEHAVIOURS,

                "drinking": DRINKING_BEHAVIOURS,

                "reaching_behind": REACHING_BEHAVIOURS,

                "passenger_talk": PASSENGER_BEHAVIOURS,

                "turning": TURNING_BEHAVIOURS,
            }

            if name in behavior_groups:

                active = (
                    readings.source == "trained_model"
                    and behavior in behavior_groups[name]
                )

            elif name == "yawning":
                active = readings.yawning

            elif name == "looking_away":
                active = readings.looking_away

            else:
                active = False

            self.durations[name] = (
                self.durations[name] + elapsed
                if active else 0.0
            )

    def _reset_behavior_durations(self):

        self.durations = dict.fromkeys(
            self.DURATION_FIELDS,
            0.0,
        )

        self.phone_use_gap = 0.0

    # -----------------------------------------------------
    # MAIN RISK UPDATE
    # -----------------------------------------------------

    def update(self, readings, elapsed=1.0):
        """Update risk from the latest measurements."""

        self._validate_readings(readings)

        if not _finite_number(elapsed) or elapsed < 0:
            raise ValueError(
                "elapsed must be a finite non-negative number."
            )

        current_source = (
            readings.source,
            readings.motion_source,
        )

        if self.source != current_source:

            self.__init__(self.attention_policy)

            self.source = current_source

        elapsed = min(float(elapsed), 2.0)

        self.observed_time += elapsed

        while (
            self.yawn_starts
            and self.observed_time - self.yawn_starts[0] > 60
        ):
            self.yawn_starts.popleft()

        # -------------------------------------------------
        # Assessment unavailable
        # -------------------------------------------------

        if not readings.assessment_available:

            self._reset_behavior_durations()

            self.previous = RiskResult(
                0,
                "UNKNOWN",
                readings.assessment_note
                or "Driver behavior assessment unavailable",
            )

            self.recovery = 0.0
            self.was_yawning = False
            self.yawn_starts.clear()

            self.speed_context = SpeedContext(
                self.attention_policy
            )

            return self.previous

        # -------------------------------------------------
        # Drowsiness availability
        # -------------------------------------------------

        if (
            not readings.drowsiness_available
            or not readings.face_detected
        ):
            self.durations["eyes_closed"] = 0.0

        # -------------------------------------------------
        # Speed context
        # -------------------------------------------------

        speed_available = (
            readings.motion_source != "phone_gps"
            or readings.speed_method in (
                "GPS",
                "GPS estimate",
            )
        )

        band_changed = False

        if speed_available:

            band_changed = self.speed_context.update(
                readings.speed,
                elapsed,
            )

        else:

            self.speed_context = SpeedContext(
                self.attention_policy
            )

        # -------------------------------------------------
        # Update behaviour durations
        # -------------------------------------------------

        self._update_durations(
            readings,
            elapsed,
        )

        # A stopped vehicle suppresses motion-related
        # warnings, but never suppresses drowsiness warnings.

        stopped = (
            speed_available
            and readings.speed < 3
        )

        if stopped:

            for name in (
                "phone_use",
                "texting",
                "phone_call",
                "radio",
                "drinking",
                "reaching_behind",
                "passenger_talk",
                "looking_away",
                "turning",
            ):

                self.durations[name] = 0.0

            self.phone_use_gap = 0.0

        # -------------------------------------------------
        # Attention warning policy
        # -------------------------------------------------

        attention_active = (
            not stopped
            and (
                readings.looking_away
                or (
                    readings.source == "trained_model"
                    and readings.behavior == "turning"
                )
            )
        )

        attention_allowed = (
            not stopped
            and speed_available
            and self.speed_context.allows_attention_warning(
                readings.speed
            )
        )

        if band_changed or not attention_allowed:

            self.durations["looking_away"] = 0.0
            self.durations["turning"] = 0.0

        # -------------------------------------------------
        # Yawning episodes
        # -------------------------------------------------

        if readings.yawning and not self.was_yawning:

            self.yawn_starts.append(
                self.observed_time
            )

        self.was_yawning = readings.yawning

        # -------------------------------------------------
        # SCORE
        # -------------------------------------------------

        score = 0
        reasons = []

        # -------------------------------------------------
        # DROWSINESS ALERTS
        # -------------------------------------------------

        if (
            readings.drowsiness_available
            and readings.face_detected
        ):

            if readings.drowsiness_alert_level == "CRITICAL":

                score += 90

                reasons.append(
                    "CRITICAL drowsiness: prolonged eye closure "
                    f"({readings.closed_duration:.1f}s)"
                )

            elif readings.drowsiness_alert_level == "WARNING":

                score += 65

                reasons.append(
                    "WARNING drowsiness: prolonged eye closure "
                    f"({readings.closed_duration:.1f}s)"
                )

        elif (
            readings.source == "simulation"
            and self.durations["eyes_closed"] >= 2
        ):

            score += 75

            reasons.append(
                "Prolonged eye closure "
                f"({self.durations['eyes_closed']:.1f}s)"
            )

        # -------------------------------------------------
        # NINE-CLASS BEHAVIOUR RULES
        # -------------------------------------------------

        for name, threshold, points, label in self.RULES:

            duration = self.durations[name]

            if duration >= threshold:

                score += points

                if (
                    readings.source == "trained_model"
                    and name == "phone_use"
                ):
                    label = "Sustained predicted phone use"

                reasons.append(
                    f"{label} ({duration:.1f}s)"
                )

        # -------------------------------------------------
        # EXTRA PHONE USE PENALTY
        # -------------------------------------------------

        if self.durations["phone_use"] >= 5:

            score += 15

        if self.durations["texting"] >= 5:

            score += 15

        # -------------------------------------------------
        # ATTENTION / TURNING RULES
        # -------------------------------------------------

        if attention_active and attention_allowed:

            caution_after, high_after = (
                self.speed_context.thresholds()
            )

            duration = max(
                self.durations["looking_away"],
                self.durations["turning"],
            )

            if duration >= caution_after:

                score += (
                    75
                    if duration >= high_after
                    else 45
                )

                label = (
                    "Turning prediction"
                    if readings.source == "trained_model"
                    else "Looking away"
                )

                reasons.append(
                    f"{label} for {duration:.1f}s "
                    f"at {readings.speed:.0f} km/h "
                    f"({self.speed_context.band} speed)"
                )

        # -------------------------------------------------
        # REPEATED YAWNING
        # -------------------------------------------------

        if len(self.yawn_starts) >= 3:

            score += 35

            reasons.append(
                "Repeated yawning "
                "(3 or more episodes within 60s)"
            )

        # -------------------------------------------------
        # HARSH DECELERATION
        # -------------------------------------------------

        if readings.acceleration <= -4:

            score += 35

            reasons.append(
                "Harsh deceleration"
            )

        # -------------------------------------------------
        # FINAL RISK LEVEL
        # -------------------------------------------------

        score = min(score, 100)

        level = (
            "HIGH" if score >= 70
            else "CAUTION" if score >= 30
            else "LOW"
        )

        # -------------------------------------------------
        # DEFAULT EXPLANATION
        # -------------------------------------------------

        default_reason = (
            "No sustained modeled risk; drowsiness unavailable"
            if (
                readings.source == "trained_model"
                and not readings.drowsiness_available
            )
            else "No sustained risky behavior"
        )

        if not speed_available:

            default_reason = (
                "GPS speed unavailable; "
                "speed-dependent warnings suppressed"
            )

        elif stopped and not reasons:

            default_reason = (
                "Vehicle stopped; motion-related alerts suppressed"
            )

        elif (
            attention_active
            and not attention_allowed
            and not reasons
        ):

            default_reason = (
                f"Possible low-speed manoeuvring at "
                f"{readings.speed:.0f} km/h; "
                "attention warning suppressed"
            )

        elif attention_active and not reasons:

            caution_after, _ = (
                self.speed_context.thresholds()
            )

            default_reason = (
                f"Attention timer below {caution_after:.0f}s threshold "
                f"at {readings.speed:.0f} km/h "
                f"({self.speed_context.band} speed)"
            )

        candidate = RiskResult(
            score,
            level,
            "; ".join(reasons) or default_reason,
        )

        # -------------------------------------------------
        # RECOVERY / HYSTERESIS
        # -------------------------------------------------

        if (
            self.LEVEL_RANKS[level]
            < self.LEVEL_RANKS[self.previous.level]
        ):

            self.recovery += elapsed

            if self.recovery < 3:

                return RiskResult(
                    self.previous.score,
                    self.previous.level,
                    "Recovering: " + self.previous.reason,
                )

        else:

            self.recovery = 0.0

        self.previous = candidate

        return candidate
