
"""Speed context for attention warnings. Values are lab defaults to calibrate."""

import math
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

    def __post_init__(self):
        """Reject invalid policy configurations."""
        values = (
            self.manoeuvring_max,
            self.moderate_max,
            self.speed_margin,
            self.transition_seconds,
            self.moderate_caution,
            self.moderate_high,
            self.fast_caution,
            self.fast_high,
        )

        for value in values:
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value < 0
            ):
                raise ValueError("Attention policy values must be finite and non-negative.")

        if self.manoeuvring_max >= self.moderate_max:
            raise ValueError(
                "manoeuvring_max must be lower than moderate_max."
            )

        if self.moderate_caution > self.moderate_high:
            raise ValueError(
                "moderate_caution cannot exceed moderate_high."
            )

        if self.fast_caution > self.fast_high:
            raise ValueError(
                "fast_caution cannot exceed fast_high."
            )


class SpeedContext:
    """Hysteresis and dwell time prevent band changes from speed noise."""

    VALID_BANDS = ("manoeuvring", "moderate", "fast")

    def __init__(self, policy):
        if not isinstance(policy, AttentionPolicy):
            raise TypeError("policy must be an AttentionPolicy instance.")

        self.policy = policy
        self.band = None
        self.pending = None
        self.pending_seconds = 0.0

    def update(self, speed, elapsed):
        """Update the speed band; return True when a transition completes."""

        for name, value in (("speed", speed), ("elapsed", elapsed)):
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
            ):
                raise ValueError(f"{name} must be a finite number.")

        if speed < 0:
            raise ValueError("speed cannot be negative.")

        if elapsed < 0:
            raise ValueError("elapsed cannot be negative.")

        p = self.policy

        if self.band is None:
            if speed <= p.manoeuvring_max:
                self.band = "manoeuvring"
            elif speed <= p.moderate_max:
                self.band = "moderate"
            else:
                self.band = "fast"

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
        """Return caution and high thresholds for the current speed band."""

        if self.band == "fast":
            return (
                self.policy.fast_caution,
                self.policy.fast_high,
            )

        return (
            self.policy.moderate_caution,
            self.policy.moderate_high,
        )

    def allows_attention_warning(self, speed):
        """Determine whether speed permits attention warnings."""

        if (
            isinstance(speed, bool)
            or not isinstance(speed, (int, float))
            or not math.isfinite(speed)
            or speed < 0
        ):
            raise ValueError("speed must be a finite non-negative number.")

        return (
            speed > self.policy.manoeuvring_max
            and self.band != "manoeuvring"
        )
