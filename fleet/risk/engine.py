
"""Explainable temporal rules. These are prototype rules, not a trained model."""

import math
from collections import deque
from dataclasses import asdict, dataclass

from .attention import AttentionPolicy, SpeedContext


CLASSIFIER_LABELS = (
    "",
    "safe_driving",
    "texting_phone",
    "talking_phone",
    "turning",
    "other_activities",
)

BEHAVIOUR_LABELS = CLASSIFIER_LABELS + (
    "unconfirmed_activity",
    "possible_call",
)

MEASUREMENT_SOURCES = ("simulation", "trained_model")
MOTION_SOURCES = ("simulation", "phone_gps")
SPEED_METHODS = ("", "GPS", "GPS estimate", "unavailable")

PHONE_USE_RELEASE_GRACE = 0.75


def _finite_number(value):
    """Check for finite numeric values, excluding booleans."""
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
            "eyes_closed", "yawning", "looking_away",
            "phone_use", "assessment_available",
        )

        for name in boolean_fields:
            value = values.get(name, getattr(result, name))
            if type(value) is not bool:
                raise ValueError(f"{name} must be true or false.")
            setattr(result, name, value)

        result.source = values.get("source", "simulation")
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

        result.classifier_label = values.get("classifier_label", "")
        if (
            not isinstance(result.classifier_label, str)
            or result.classifier_label not in CLASSIFIER_LABELS
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
                    raise ValueError(f"Invalid {name} vector.")
                vector = [float(v) for v in vector]
            setattr(result, name, vector)

        numeric_fields = {
            "speed": (0, 250),
            "acceleration": (-20, 20),
            "confidence": (0, 1),
            "classifier_score": (0, 1),
            "inference_ms": (0, 600000),
        }

        for name, (minimum, maximum) in numeric_fields.items():
            value = values.get(name, getattr(result, name))
            if not _finite_number(value) or not minimum <= value <= maximum:
                raise ValueError(
                    f"{name} must be between {minimum} and {maximum}."
                )
            setattr(result, name, float(value))

        result.motion_source = values.get("motion_source", "simulation")
        if result.motion_source not in MOTION_SOURCES:
            raise ValueError("Unknown motion source.")

        result.speed_method = values.get("speed_method", "")
        if result.speed_method not in SPEED_METHODS:
            raise ValueError("Unknown speed measurement method.")

        if result.motion_source == "phone_gps" and result.acceleration != 0:
            raise ValueError(
                "Phone GPS does not measure acceleration in this version."
            )

        result.behavior = values.get("behavior", "")
        if result.behavior not in BEHAVIOUR_LABELS:
            raise ValueError("Unknown behavior class.")

        note = values.get("assessment_note", "")
        if not isinstance(note, str) or len(note) > 250:
            raise ValueError("Invalid assessment note.")
        result.assessment_note = note

        result.face_activity = values.get("face_activity", "")
        if result.face_activity not in (
            "", "Eyes closed", "Looking aside", "Facing forward"
        ):
            raise ValueError("Invalid face activity.")

        if result.source == "trained_model" and (
            result.eyes_closed
            or result.yawning
            or result.face_visible is not None
            or result.face_activity
        ):
            raise ValueError(
                "This classifier does not measure eyes, yawns, "
                "or face visibility."
            )

        return result

    def to_dict(self):
        return asdict(self)


@dataclass
class RiskResult:
    score: int
    level: str
    reason: str

    def to_dict(self):
        return asdict(self)


class RiskEngine:
    """Accumulate behavior duration and require recovery before clearing risk."""

    DURATION_FIELDS = (
        "eyes_closed", "yawning", "looking_away", "phone_use", "turning"
    )

    RULES = (
        ("eyes_closed", 2, 75, "Prolonged eye closure"),
        ("phone_use", 2, 65, "Sustained phone use"),
        ("yawning", 2, 25, "Sustained yawning"),
    )

    LEVEL_RANKS = {
        "UNKNOWN": -1,
        "LOW": 0,
        "CAUTION": 1,
        "HIGH": 2,
    }

    def __init__(self, attention_policy=None):
        self.attention_policy = attention_policy or AttentionPolicy()
        self.speed_context = SpeedContext(self.attention_policy)
        self.durations = dict.fromkeys(self.DURATION_FIELDS, 0.0)
        self.phone_use_gap = 0.0
        self.source = None
        self.previous = RiskResult(
            0, "LOW", "No sustained risky behavior"
        )
        self.recovery = 0.0
        self.observed_time = 0.0
        self.yawn_starts = deque()
        self.was_yawning = False

    @staticmethod
    def _validate_readings(readings):
        """Validate fields consumed by the risk engine."""
        if not isinstance(readings, Measurements):
            raise TypeError("readings must be a Measurements instance.")

        for name, minimum, maximum in (
            ("speed", 0, 250),
            ("acceleration", -20, 20),
        ):
            value = getattr(readings, name)
            if not _finite_number(value) or not minimum <= value <= maximum:
                raise ValueError(f"Invalid measurement: {name}.")

        for name in (
            "eyes_closed", "yawning", "looking_away",
            "phone_use", "assessment_available",
        ):
            if type(getattr(readings, name)) is not bool:
                raise ValueError(f"{name} must be true or false.")

        if readings.source not in MEASUREMENT_SOURCES:
            raise ValueError("Unknown measurement source.")
        if readings.motion_source not in MOTION_SOURCES:
            raise ValueError("Unknown motion source.")
        if readings.speed_method not in SPEED_METHODS:
            raise ValueError("Unknown speed measurement method.")
        if readings.behavior not in BEHAVIOUR_LABELS:
            raise ValueError("Unknown behavior class.")

    def _update_durations(self, readings, elapsed):
        """Update accumulated behavior durations."""
        for name in self.DURATION_FIELDS:
            if name == "phone_use":
                if readings.phone_use:
                    self.durations[name] += elapsed
                    self.phone_use_gap = 0.0
                elif self.durations[name] > 0:
                    self.phone_use_gap += elapsed
                    if self.phone_use_gap <= PHONE_USE_RELEASE_GRACE:
                        self.durations[name] += elapsed
                    else:
                        self.durations[name] = 0.0
                        self.phone_use_gap = 0.0
                continue

            active = (
                readings.behavior == "turning"
                if name == "turning" and readings.source == "trained_model"
                else getattr(readings, name)
            )
            self.durations[name] = (
                self.durations[name] + elapsed if active else 0.0
            )

    def _reset_behavior_durations(self):
        self.durations = dict.fromkeys(self.DURATION_FIELDS, 0.0)
        self.phone_use_gap = 0.0

    def update(self, readings, elapsed=1.0):
        """Process one measurement and return the current risk result."""
        self._validate_readings(readings)

        if not _finite_number(elapsed) or elapsed < 0:
            raise ValueError("elapsed must be a finite non-negative number.")

        current_source = (readings.source, readings.motion_source)
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

        # Behavior assessment unavailable.
        if not readings.assessment_available or readings.face_visible is False:
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
            self.speed_context = SpeedContext(self.attention_policy)
            return self.previous

        # GPS speed availability is independent of behavior availability.
        speed_available = (
            readings.motion_source != "phone_gps"
            or readings.speed_method in ("GPS", "GPS estimate")
        )

        band_changed = False
        if speed_available:
            band_changed = self.speed_context.update(readings.speed, elapsed)
        else:
            self.speed_context = SpeedContext(self.attention_policy)

        self._update_durations(readings, elapsed)

        # Suppress behavior warnings only when a stop is confirmed.
        if speed_available and readings.speed < 3:
            self._reset_behavior_durations()
            self.previous = RiskResult(
                0, "LOW",
                "Vehicle stopped; motion-related alerts suppressed",
            )
            self.recovery = 0.0
            self.yawn_starts.clear()
            self.was_yawning = False
            self.speed_context = SpeedContext(self.attention_policy)
            return self.previous

        attention_active = (
            readings.looking_away
            or (
                readings.source == "trained_model"
                and readings.behavior == "turning"
            )
        )
        attention_allowed = (
            speed_available
            and self.speed_context.allows_attention_warning(readings.speed)
        )

        if band_changed or not attention_allowed:
            self.durations["looking_away"] = 0.0
            self.durations["turning"] = 0.0

        if readings.yawning and not self.was_yawning:
            self.yawn_starts.append(self.observed_time)
        self.was_yawning = readings.yawning

        score = 0
        reasons = []

        for name, threshold, points, label in self.RULES:
            duration = self.durations[name]
            if duration >= threshold:
                score += points
                if readings.source == "trained_model" and name == "phone_use":
                    label = "Sustained predicted phone use"
                reasons.append(f"{label} ({duration:.1f}s)")

        if attention_active and attention_allowed:
            caution_after, high_after = self.speed_context.thresholds()
            duration = max(
                self.durations["looking_away"],
                self.durations["turning"],
            )

            if duration >= caution_after:
                score += 75 if duration >= high_after else 45
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

        if self.durations["phone_use"] >= 5:
            score += 15

        if len(self.yawn_starts) >= 3:
            score += 35
            reasons.append(
                "Repeated yawning (3 or more episodes within 60s)"
            )

        if readings.acceleration <= -4:
            score += 35
            reasons.append("Harsh deceleration")

        score = min(score, 100)
        level = (
            "HIGH" if score >= 70
            else "CAUTION" if score >= 30
            else "LOW"
        )

        default_reason = (
            "No sustained modeled risk; drowsiness is not measured"
            if readings.source == "trained_model"
            else "No sustained risky behavior"
        )

        if not speed_available:
            default_reason = (
                "GPS speed unavailable; speed-dependent warnings suppressed"
            )
        elif attention_active and not attention_allowed:
            default_reason = (
                f"Possible low-speed manoeuvring at {readings.speed:.0f} km/h; "
                "attention warning suppressed"
            )
        elif attention_active and not reasons:
            caution_after, _ = self.speed_context.thresholds()
            default_reason = (
                f"Attention timer below {caution_after:.0f}s threshold "
                f"at {readings.speed:.0f} km/h "
                f"({self.speed_context.band} speed)"
            )

        candidate = RiskResult(
            score, level, "; ".join(reasons) or default_reason
        )

        if self.LEVEL_RANKS[level] < self.LEVEL_RANKS[self.previous.level]:
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
