
"""Validation of mobile application assets."""

import logging

from .mobile_config import (
    MOBILE_PAGE,
    MOBILE_CSS,
    MOBILE_JS,
    MOBILE_MODEL,
)


# Required browser JavaScript files.
REQUIRED_JS_FILES = (
    "config.js",
    "ui.js",
    "sensors.js",
    "camera.js",
    "drowsiness.js",
    "inference.js",
    "main.js",
)


def _validate_file(path, description):
    """Validate that a required file exists, is readable and is not empty."""

    if not path.is_file():
        raise FileNotFoundError(
            f"{description} not found: {path}"
        )

    if path.stat().st_size <= 0:
        raise ValueError(
            f"{description} is empty: {path}"
        )

    try:
        with path.open("rb") as file:
            file.read(1)
    except OSError as error:
        raise OSError(
            f"{description} cannot be read: {path}"
        ) from error


def validate_mobile_assets():
    """Check that all browser assets and required models exist."""

    required_files = (
        (MOBILE_PAGE, "Mobile HTML page"),
        (MOBILE_CSS / "mobile.css", "Mobile CSS"),
        *((MOBILE_JS / filename, f"Mobile JavaScript ({filename})")
          for filename in REQUIRED_JS_FILES),
    )

    # Validate HTML, CSS, and JavaScript files.
    for path, description in required_files:
        _validate_file(path, description)

    # Validate the behaviour classification model.
    if MOBILE_MODEL.suffix.lower() != ".onnx":
        raise ValueError(
            f"Behaviour model must be an ONNX file: {MOBILE_MODEL}"
        )

    _validate_file(
        MOBILE_MODEL,
        "Browser ONNX behaviour model",
    )

    # Validate the face-landmarker model if configured.
    face_model = MOBILE_MODEL.parent / "face_landmarker.task"

    if face_model.exists():
        _validate_file(
            face_model,
            "Face landmarker model",
        )
    else:
        logging.warning(
            "Face landmarker model not found: %s",
            face_model,
        )

    model_size = MOBILE_MODEL.stat().st_size

    logging.info("Mobile page: %s", MOBILE_PAGE)
    logging.info("Mobile CSS: %s", MOBILE_CSS)
    logging.info("Mobile JavaScript: %s", MOBILE_JS)

    logging.info(
        "Browser ONNX model: %s (%.2f MB)",
        MOBILE_MODEL,
        model_size / (1024 * 1024),
    )

    if face_model.is_file():
        logging.info(
            "Face landmarker model: %s (%.2f MB)",
            face_model,
            face_model.stat().st_size / (1024 * 1024),
        )

    logging.info(
        "Mobile application assets validated successfully."
    )
