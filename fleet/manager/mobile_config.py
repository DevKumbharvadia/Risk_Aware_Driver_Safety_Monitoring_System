
"""Paths and limits for the mobile phone application."""

from pathlib import Path


# ---------------------------------------------------------------------
# Project paths
# ---------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]

MOBILE_ROOT = PROJECT_ROOT / "fleet" / "mobile"

MOBILE_PAGE = MOBILE_ROOT / "mobile.html"
MOBILE_CSS = MOBILE_ROOT / "css"
MOBILE_JS = MOBILE_ROOT / "js"

MODELS_DIR = PROJECT_ROOT / "models"

# Driver behaviour classification model.
MOBILE_MODEL = (
    MODELS_DIR
    / "driver_mobilenetv3_small.onnx"
)

# Face landmark model used for drowsiness detection.
FACE_LANDMARKER_MODEL = (
    MODELS_DIR
    / "face_landmarker.task"
)


# ---------------------------------------------------------------------
# Request size limits
# ---------------------------------------------------------------------

MAX_PREDICTION_BYTES = 32_000
MAX_PREVIEW_BYTES = 250_000


# ---------------------------------------------------------------------
# Prediction timing limits (seconds)
# ---------------------------------------------------------------------

PREDICTION_MAX_AGE = 5.0

PREDICTION_FUTURE_TOLERANCE = 1.0

PREDICTION_STALE_OVERLAY = 2.5


# ---------------------------------------------------------------------
# Configuration validation
# ---------------------------------------------------------------------

def validate_mobile_config():
    """Validate mobile application configuration values."""

    positive_limits = {
        "MAX_PREDICTION_BYTES": MAX_PREDICTION_BYTES,
        "MAX_PREVIEW_BYTES": MAX_PREVIEW_BYTES,
        "PREDICTION_MAX_AGE": PREDICTION_MAX_AGE,
        "PREDICTION_STALE_OVERLAY": PREDICTION_STALE_OVERLAY,
    }

    for name, value in positive_limits.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError(
                f"{name} must be a number."
            )

        if value <= 0:
            raise ValueError(
                f"{name} must be greater than zero."
            )

    if (
        isinstance(PREDICTION_FUTURE_TOLERANCE, bool)
        or not isinstance(PREDICTION_FUTURE_TOLERANCE, (int, float))
        or PREDICTION_FUTURE_TOLERANCE < 0
    ):
        raise ValueError(
            "PREDICTION_FUTURE_TOLERANCE must be a non-negative number."
        )

    if MAX_PREVIEW_BYTES < MAX_PREDICTION_BYTES:
        raise ValueError(
            "MAX_PREVIEW_BYTES should not be smaller than "
            "MAX_PREDICTION_BYTES."
        )

    if PREDICTION_STALE_OVERLAY > PREDICTION_MAX_AGE:
        raise ValueError(
            "PREDICTION_STALE_OVERLAY should not exceed "
            "PREDICTION_MAX_AGE."
        )
