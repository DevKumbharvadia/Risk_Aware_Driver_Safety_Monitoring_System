"""Explainable temporal rules. These are prototype rules, not a trained model."""
from dataclasses import asdict, dataclass
from collections import deque
from .attention import AttentionPolicy, SpeedContext


@dataclass
class Measurements:
    # A visible object alone does not establish how the driver is using it.
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
    # Raw phone sensor vectors, in handset coordinates.
    accelerometer: list | None = None
    gyroscope: list | None = None
    handset_visible: bool | None = None
    classifier_label: str = ""
    classifier_score: float = 0.0

    @classmethod
    def from_dict(cls, values):
        if not isinstance(values, dict):
            raise ValueError("Measurements must be an object.")
        result = cls()
        for name in ("eyes_closed", "yawning", "looking_away", "phone_use", "assessment_available"):
            value = values.get(name, getattr(result, name))
            if not isinstance(value, bool):
                raise ValueError(f"{name} must be true or false.")
            setattr(result, name, value)
        face = values.get("face_visible", True)
        if type(face) is not bool and not (face is None and values.get("source") == "trained_model"):
            raise ValueError("Face visibility must be boolean, or unmeasured for the classifier.")
        result.face_visible = face
        handset = values.get("handset_visible")
        if handset is not None and type(handset) is not bool:
            raise ValueError("Handset visibility must be boolean or unmeasured.")
        result.handset_visible = handset
        result.classifier_label = values.get("classifier_label", "")
        if result.classifier_label not in ("", "safe_driving", "texting_phone", "talking_phone", "turning", "other_activities"):
            raise ValueError("Unknown raw classifier label.")
        import math
        for name in ("accelerometer", "gyroscope"):
            vector = values.get(name)
            if vector is not None and (not isinstance(vector, list) or len(vector) != 3 or
                    any(type(v) not in (float, int) or not math.isfinite(v) for v in vector)):
                raise ValueError(f"Invalid {name} vector.")
            setattr(result, name, vector)
        for name, minimum, maximum in (("speed", 0, 250), ("acceleration", -20, 20),
                                       ("confidence", 0, 1), ("classifier_score", 0, 1), ("inference_ms", 0, 600_000)):
            value = values.get(name, 0)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not minimum <= value <= maximum:
                raise ValueError(f"{name} must be between {minimum} and {maximum}.")
            setattr(result, name, float(value))
        if values.get("source", "simulation") not in ("simulation", "trained_model"):
            raise ValueError("Unknown measurement source.")
        result.source = values.get("source", "simulation")
        if values.get("motion_source", "simulation") not in ("simulation", "phone_gps"):
            raise ValueError("Unknown motion source.")
        result.motion_source = values.get("motion_source", "simulation")
        result.speed_method = values.get("speed_method", "")
        if result.speed_method not in ("", "GPS", "GPS estimate", "unavailable"):
            raise ValueError("Unknown speed measurement method.")
        if result.motion_source == "phone_gps" and result.acceleration != 0:
            raise ValueError("Phone GPS does not measure acceleration in this version.")
        behavior = values.get("behavior", "")
        if behavior not in ("", "safe_driving", "talking_phone", "texting_phone", "turning", "other_activities", "unconfirmed_activity", "possible_call"):
            raise ValueError("Unknown behavior class.")
        result.behavior = behavior
        note = values.get("assessment_note", "")
        if not isinstance(note, str) or len(note) > 250:
            raise ValueError("Invalid assessment note.")
        result.assessment_note = note
        result.face_activity = values.get("face_activity", "")
        if result.face_activity not in ("", "Eyes closed", "Looking aside", "Facing forward"):
            raise ValueError("Invalid face activity.")
        if result.source == "trained_model" and ((result.eyes_closed and result.face_activity != "Eyes closed") or result.yawning or result.face_visible is not None):
            raise ValueError("This classifier does not measure eyes, yawns, or face visibility.")
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

    def __init__(self, attention_policy=None):
        self.attention_policy = attention_policy or AttentionPolicy()
        self.speed_context = SpeedContext(self.attention_policy)
        self.durations = {name: 0.0 for name in ("eyes_closed", "yawning", "looking_away", "phone_use", "turning")}
        self.source = None
        self.previous = RiskResult(0, "LOW", "No sustained risky behavior")
        self.recovery = 0.0
        self.observed_time = 0.0
        self.yawn_starts = deque()
        self.was_yawning = False

    def update(self, readings, elapsed=1.0):
        if self.source != (readings.source, readings.motion_source):
            self.__init__(self.attention_policy)
            self.source = (readings.source, readings.motion_source)
        # A long disconnected interval must not count as observed behavior.
        elapsed = max(0.0, min(float(elapsed), 2.0))
        self.observed_time += elapsed
        while self.yawn_starts and self.observed_time - self.yawn_starts[0] > 60:
            self.yawn_starts.popleft()
        if not readings.assessment_available or readings.face_visible is False:
            self.durations = dict.fromkeys(self.durations, 0.0)
            self.previous = RiskResult(0, "UNKNOWN", readings.assessment_note or "Face unavailable; driver state cannot be assessed")
            self.recovery = 0
            self.was_yawning = False
            self.yawn_starts.clear()
            self.speed_context = SpeedContext(self.attention_policy)
            return self.previous
        band_changed = self.speed_context.update(readings.speed, elapsed)
        for name in self.durations:
            active = (readings.source == "trained_model" and readings.behavior == "turning") if name == "turning" else getattr(readings, name)
            self.durations[name] = self.durations[name] + elapsed if active else 0.0
        if readings.speed < 3:
            self.durations = dict.fromkeys(self.durations, 0.0)
            self.previous = RiskResult(0, "LOW", "Vehicle stopped; motion-related alerts suppressed")
            self.recovery = 0
            self.yawn_starts.clear()
            self.was_yawning = False
            self.speed_context = SpeedContext(self.attention_policy)
            return self.previous
        attention_active = readings.looking_away or (readings.source == "trained_model" and readings.behavior == "turning")
        attention_allowed = self.speed_context.allows_attention_warning(readings.speed)
        if band_changed or not attention_allowed:
            # Manoeuvring time must not suddenly become a warning when accelerating.
            self.durations["looking_away"] = 0.0
            self.durations["turning"] = 0.0
        if readings.yawning and not self.was_yawning:
            self.yawn_starts.append(self.observed_time)
        self.was_yawning = readings.yawning
        reasons = []
        score = 0
        rules = (("eyes_closed", 2, 75, "Prolonged eye closure"),
                 ("phone_use", 2, 65, "Sustained phone use"),
                 ("yawning", 2, 25, "Sustained yawning"))
        for name, threshold, points, label in rules:
            if self.durations[name] >= threshold:
                score += points
                if readings.source == "trained_model" and name == "phone_use":
                    label = "Sustained predicted phone use"
                reasons.append(f"{label} ({self.durations[name]:.0f}s)")
        if attention_active and attention_allowed:
            caution_after, high_after = self.speed_context.thresholds()
            duration = max(self.durations["looking_away"], self.durations["turning"])
            if duration >= caution_after:
                score += 75 if duration >= high_after else 45
                label = "Turning prediction" if readings.source == "trained_model" else "Looking away"
                reasons.append(f"{label} for {duration:.1f}s at {readings.speed:.0f} km/h ({self.speed_context.band} speed)")
        if self.durations["phone_use"] >= 5:
            score += 15
        if len(self.yawn_starts) >= 3:
            score += 35
            reasons.append("Repeated yawning (3 or more episodes within 60s)")
        if readings.acceleration <= -4:
            score += 35
            reasons.append("Harsh deceleration")
        score = min(score, 100)
        level = "HIGH" if score >= 70 else "CAUTION" if score >= 30 else "LOW"
        default_reason = "No sustained modeled risk; drowsiness is not measured" if readings.source == "trained_model" else "No sustained risky behavior"
        if attention_active and not attention_allowed:
            default_reason = f"Possible low-speed manoeuvring at {readings.speed:.0f} km/h; attention warning suppressed"
        elif attention_active and not reasons:
            caution_after, _ = self.speed_context.thresholds()
            default_reason = f"Attention timer below {caution_after:.0f}s threshold at {readings.speed:.0f} km/h ({self.speed_context.band} speed)"
        candidate = RiskResult(score, level, "; ".join(reasons) or default_reason)
        ranks = {"UNKNOWN": -1, "LOW": 0, "CAUTION": 1, "HIGH": 2}
        if ranks[level] < ranks[self.previous.level]:
            self.recovery += elapsed
            if self.recovery < 3:
                return RiskResult(self.previous.score, self.previous.level, "Recovering: " + self.previous.reason)
        else:
            self.recovery = 0
        self.previous = candidate
        return candidate
