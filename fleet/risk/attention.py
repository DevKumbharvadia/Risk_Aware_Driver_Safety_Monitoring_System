"""Speed context for attention warnings. Values are lab defaults to calibrate."""
from dataclasses import dataclass


@dataclass(frozen=True)
class AttentionPolicy:
    manoeuvring_max: float = 10.0
    moderate_max: float = 30.0
    speed_margin: float = 2.0
    transition_seconds: float = 2.0
    moderate_caution: float = 5.0
    moderate_high: float = 10.0
    fast_caution: float = 3.0
    fast_high: float = 6.0


class SpeedContext:
    """Hysteresis and a dwell time prevent band changes from speed noise."""
    def __init__(self, policy):
        self.policy = policy
        self.band = None
        self.pending = None
        self.pending_seconds = 0.0

    def update(self, speed, elapsed):
        p = self.policy
        if self.band is None:
            self.band = "manoeuvring" if speed <= p.manoeuvring_max else "moderate" if speed <= p.moderate_max else "fast"
            return False
        candidate = self.band
        if self.band == "manoeuvring":
            if speed > p.moderate_max + p.speed_margin:
                candidate = "fast"
            elif speed > p.manoeuvring_max + p.speed_margin:
                candidate = "moderate"
        elif self.band == "moderate":
            if speed <= p.manoeuvring_max - p.speed_margin:
                candidate = "manoeuvring"
            elif speed > p.moderate_max + p.speed_margin:
                candidate = "fast"
        else:
            if speed <= p.manoeuvring_max - p.speed_margin:
                candidate = "manoeuvring"
            elif speed <= p.moderate_max - p.speed_margin:
                candidate = "moderate"

        if candidate == self.band:
            self.pending = None
            self.pending_seconds = 0.0
            return False
        if candidate != self.pending:
            self.pending = candidate
            self.pending_seconds = 0.0
        self.pending_seconds += elapsed
        if self.pending_seconds < p.transition_seconds:
            return False
        self.band = candidate
        self.pending = None
        self.pending_seconds = 0.0
        return True

    def thresholds(self):
        if self.band == "fast":
            return self.policy.fast_caution, self.policy.fast_high
        return self.policy.moderate_caution, self.policy.moderate_high

    def allows_attention_warning(self, speed):
        # Even before a band transition settles, low speed gets the allowance.
        return speed > self.policy.manoeuvring_max and self.band != "manoeuvring"
