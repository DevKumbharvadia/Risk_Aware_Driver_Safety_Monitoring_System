
"""Speed context for attention warnings. Values are lab defaults."""

import math
from dataclasses import dataclass


def _valid_number(value):
    """Check for finite numeric values, excluding booleans."""
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


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

        if any(not _valid_number(v) or v < 0 for v in values):
            raise ValueError(
                "Attention policy values must be finite and non-negative."
            )

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
    """Use hysteresis and dwell time to prevent speed-band fluctuations."""

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
            if not _valid_number(value) or value < 0:
                raise ValueError(
                    f"{name} must be a finite non-negative number."
                )

        p = self.policy

        # Establish the initial band immediately.
        if self.band is None:
            self.band = (
                "manoeuvring" if speed <= p.manoeuvring_max
                else "moderate" if speed <= p.moderate_max
                else "fast"
            )
            return False

        if self.band not in self.VALID_BANDS:
            raise ValueError("Invalid internal speed band.")

        low = p.manoeuvring_max
        high = p.moderate_max
        margin = p.speed_margin

        # Apply hysteresis when moving between bands.
        transitions = {
            "manoeuvring": (
                (high + margin, "fast"),
                (low + margin, "moderate"),
            ),
            "moderate": (
                (low - margin, "manoeuvring"),
                (high + margin, "fast"),
            ),
            "fast": (
                (low - margin, "manoeuvring"),
                (high - margin, "moderate"),
            ),
        }

        candidate = self.band

        for boundary, target in transitions[self.band]:
            if (
                (target == "fast" and speed > boundary)
                or (target != "fast" and speed <= boundary)
            ):
                candidate = target
                break

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
        """Return caution and high thresholds for the current band."""

        if self.band == "fast":
            return self.policy.fast_caution, self.policy.fast_high

        if self.band == "moderate":
            return self.policy.moderate_caution, self.policy.moderate_high

        return None

    def allows_attention_warning(self, speed):
        """Check whether speed permits attention warnings."""

        if not _valid_number(speed) or speed < 0:
            raise ValueError(
                "speed must be a finite non-negative number."
            )

        return (
            speed > self.policy.manoeuvring_max
            and self.band in ("moderate", "fast")
        )
