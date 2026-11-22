
"""Validation of mobile application assets."""

import logging

from .mobile_config import (
    MOBILE_PAGE,
    MOBILE_CSS,
    MOBILE_JS,
    MOBILE_MODEL,
)


def validate_mobile_assets():
    """Check that all browser assets and the ONNX model exist."""

    required_files = (
        MOBILE_PAGE,
        MOBILE_CSS / "mobile.css",
        MOBILE_JS / "config.js",
        MOBILE_JS / "ui.js",
        MOBILE_JS / "sensors.js",
        MOBILE_JS / "camera.js",
        MOBILE_JS / "inference.js",
        MOBILE_JS / "main.js",
    )

    missing = [path for path in required_files if not path.is_file()]

    if missing:
        raise FileNotFoundError(
            "Required mobile application files are missing:\n"
            + "\n".join(str(path) for path in missing)
        )

    if not MOBILE_MODEL.is_file():
        raise FileNotFoundError(
            f"ONNX model not found: {MOBILE_MODEL}\n"
            "Place driver_mobilenetv3_small.onnx in the models directory."
        )

    model_size = MOBILE_MODEL.stat().st_size

    if model_size <= 0:
        raise ValueError(f"ONNX model file is empty: {MOBILE_MODEL}")

    logging.info("Mobile page: %s", MOBILE_PAGE)
    logging.info("Mobile CSS: %s", MOBILE_CSS)
    logging.info("Mobile JavaScript: %s", MOBILE_JS)
    logging.info(
        "Browser ONNX model: %s (%.2f MB)",
        MOBILE_MODEL,
        model_size / (1024 * 1024),
    )
