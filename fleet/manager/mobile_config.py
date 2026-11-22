
"""Paths and limits for the mobile phone application."""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]

MOBILE_ROOT = PROJECT_ROOT / "fleet" / "mobile"
MOBILE_PAGE = MOBILE_ROOT / "mobile.html"
MOBILE_CSS = MOBILE_ROOT / "css"
MOBILE_JS = MOBILE_ROOT / "js"

MOBILE_MODEL = (
    PROJECT_ROOT
    / "models"
    / "driver_mobilenetv3_small.onnx"
)

MAX_PREDICTION_BYTES = 32_000
MAX_PREVIEW_BYTES = 250_000

PREDICTION_MAX_AGE = 5.0
PREDICTION_FUTURE_TOLERANCE = 1.0
PREDICTION_STALE_OVERLAY = 2.5
