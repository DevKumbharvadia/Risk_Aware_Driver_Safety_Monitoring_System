
"""HTTP endpoints for the smartphone browser."""

from datetime import datetime, timezone
import json
import logging
import time
from urllib.parse import unquote, urlsplit

from ..mobile.phone_speed import PhoneHandler
from .mobile_config import (
    MOBILE_ROOT,
    MOBILE_PAGE,
    MOBILE_MODEL,
    MAX_PREDICTION_BYTES,
    MAX_PREVIEW_BYTES,
    PREDICTION_STALE_OVERLAY,
)


class MobileHandler(PhoneHandler):
    """Serve mobile assets and handle authenticated phone requests."""

    def _stopping(self):
        """Check whether the server is shutting down."""

        return self.server.stopping.is_set()

    def _get_vehicle_link(self):
        """Find the phone session using its bearer token."""

        authorization = self.headers.get("Authorization", "")

        if not authorization.startswith("Bearer "):
            return None

        token = authorization[7:].strip()

        if not token:
            return None

        with self.server.links_lock:
            link = self.server.links.get(token)

        if link is not None:
            link.touch()

        return link

    @staticmethod
    def _static_asset(path):
        """Resolve CSS and JavaScript files without directory traversal."""

        decoded_path = unquote(path)

        if not decoded_path.startswith(("/css/", "/js/")):
            return None

        try:
            root = MOBILE_ROOT.resolve()

            asset_path = (
                root / decoded_path.lstrip("/")
            ).resolve()

            asset_path.relative_to(root)

        except (ValueError, OSError, RuntimeError):
            return None

        if not asset_path.is_file():
            return None

        content_types = {
            ".css": "text/css; charset=utf-8",
            ".js": "text/javascript; charset=utf-8",
        }

        content_type = content_types.get(
            asset_path.suffix.lower()
        )

        if content_type is None:
            return None

        return asset_path, content_type

    def do_GET(self):
        """Handle mobile page, asset, model, and status requests."""

        if self._stopping():
            return self.respond(
                503,
                b"Fleet Guardian is shutting down.",
            )

        path = urlsplit(self.path).path

        # -------------------------------------------------------------
        # CSS and JavaScript assets
        # -------------------------------------------------------------

        if path.startswith(("/css/", "/js/")):
            asset = self._static_asset(path)

            if asset is None:
                return self.respond(
                    404,
                    b"Mobile application asset not found.",
                )

            asset_path, content_type = asset

            try:
                content = asset_path.read_bytes()

            except OSError:
                logging.exception(
                    "Unable to read mobile asset: %s",
                    asset_path,
                )

                return self.respond(
                    500,
                    b"Unable to read mobile application asset.",
                )

            return self.respond(
                200,
                content,
                content_type,
            )

        # -------------------------------------------------------------
        # Preview control
        # -------------------------------------------------------------

        if path == "/preview-control":
            link = self._get_vehicle_link()

            if not link:
                return self.respond(
                    403,
                    b"Open the current vehicle link from the manager PC.",
                )

            fleet = self.server.fleet
            trip = fleet.store.assignment(link.vehicle)

            payload = json.dumps({
                "enabled": bool(
                    trip
                    and fleet.preview_is_selected(link.session_id)
                ),
            }).encode("utf-8")

            return self.respond(
                200,
                payload,
                "application/json",
            )

        # -------------------------------------------------------------
        # Server version
        # -------------------------------------------------------------

        if path == "/version":
            return self.respond(
                200,
                b'{"mobile":7,"inference":"browser-onnx"}',
                "application/json",
            )

        # -------------------------------------------------------------
        # Server clock
        # -------------------------------------------------------------

        if path == "/clock":
            payload = json.dumps({
                "monotonic": time.monotonic(),
            }).encode("utf-8")

            return self.respond(
                200,
                payload,
                "application/json",
            )

        # -------------------------------------------------------------
        # Browser ONNX model
        # -------------------------------------------------------------

        if path == "/models/driver_mobilenetv3_small.onnx":

            try:
                if not MOBILE_MODEL.is_file():
                    logging.error(
                        "ONNX model file not found: %s",
                        MOBILE_MODEL,
                    )

                    return self.respond(
                        404,
                        b"ONNX model not found. Check the models directory.",
                    )

                model = MOBILE_MODEL.read_bytes()

                if not model:
                    logging.error(
                        "ONNX model file is empty: %s",
                        MOBILE_MODEL,
                    )

                    return self.respond(
                        500,
                        b"ONNX model file is empty.",
                    )

            except OSError:
                logging.exception(
                    "Unable to read ONNX model: %s",
                    MOBILE_MODEL,
                )

                return self.respond(
                    500,
                    b"Unable to read ONNX model.",
                )

            return self.respond(
                200,
                model,
                "application/octet-stream",
            )

        # -------------------------------------------------------------
        # Mobile application page
        # -------------------------------------------------------------

        if path not in ("/", "/index.html"):
            return self.respond(
                404,
                b"Unknown page",
            )

        try:
            page = MOBILE_PAGE.read_bytes()

            if not page:
                return self.respond(
                    500,
                    b"Mobile page is empty.",
                )

        except OSError:
            logging.exception(
                "Could not read the mobile page: %s",
                MOBILE_PAGE,
            )

            return self.respond(
                500,
                b"Mobile page unavailable.",
            )

        return self.respond(
            200,
            page,
            "text/html; charset=utf-8",
        )

    def do_POST(self):
        """Handle authenticated phone prediction and preview requests."""

        if self._stopping():
            return self.respond(
                503,
                b"Fleet Guardian is shutting down.",
            )

        try:
            path = urlsplit(self.path).path

            if path not in ("/prediction", "/preview"):
                return self.respond(
                    404,
                    b"Unknown endpoint",
                )

            # Authenticate the phone session.
            link = self._get_vehicle_link()

            if not link:
                return self.respond(
                    403,
                    b"Open the current vehicle link from the manager PC.",
                )

            # Validate Content-Length.
            content_length = self.headers.get("Content-Length")

            if content_length is None:
                raise ValueError(
                    "Missing Content-Length header."
                )

            try:
                size = int(content_length)

            except (ValueError, TypeError):
                raise ValueError(
                    "Invalid request size."
                ) from None

            maximum = (
                MAX_PREVIEW_BYTES
                if path == "/preview"
                else MAX_PREDICTION_BYTES
            )

            if size <= 0 or size > maximum:
                raise ValueError(
                    "Invalid request size."
                )

            # Read the request body with a timeout.
            self.connection.settimeout(5)

            body = self.rfile.read(size)

            if len(body) != size:
                raise ValueError(
                    "Incomplete phone request."
                )

            if self._stopping():
                return self.respond(
                    503,
                    b"Fleet Guardian is shutting down.",
                )

            # Dispatch the request.
            if path == "/preview":
                return self._handle_preview(
                    link,
                    body,
                )

            return self._handle_prediction(
                link,
                body,
            )

        except TimeoutError as error:
            logging.warning(
                "Phone request timed out: %s",
                error,
            )

            if not self._stopping():
                return self.respond(
                    408,
                    str(error).encode("utf-8"),
                )

        except (
            ValueError,
            KeyError,
            TypeError,
            OSError,
            OverflowError,
        ) as error:

            if not self._stopping():
                logging.warning(
                    "Phone request rejected: %s",
                    error,
                )

                return self.respond(
                    400,
                    str(error).encode("utf-8"),
                )

        except RuntimeError as error:

            if not self._stopping():
                logging.info(
                    "Phone request ended: %s",
                    error,
                )

                return self.respond(
                    503,
                    str(error).encode("utf-8"),
                )

        except Exception:

            if not self._stopping():
                logging.exception(
                    "Phone prediction or preview request failed"
                )

                return self.respond(
                    500,
                    b"Prediction or fleet service unavailable. Check PC setup.",
                )

    def _handle_preview(self, link, body):
        """Validate and store a preview for its selected phone session."""

        fleet = self.server.fleet

        if not fleet.preview_is_selected(link.session_id):
            return self.respond(
                403,
                b"Camera preview is not enabled for this phone.",
            )

        trip = fleet.store.assignment(link.vehicle)

        if not trip or str(trip["id"]) != self.headers.get("X-Trip"):
            raise ValueError(
                "Trip changed."
            )

        # Validate JPEG boundaries.
        if (
            len(body) < 4
            or not body.startswith(b"\xff\xd8")
            or not body.endswith(b"\xff\xd9")
        ):
            raise ValueError(
                "Invalid JPEG preview."
            )

        # Retrieve the latest prediction overlay.
        assessed_trip, assessed_at, level = link.overlay

        overlay_age = time.monotonic() - assessed_at

        if (
            assessed_trip != trip["id"]
            or overlay_age < 0
            or overlay_age > PREDICTION_STALE_OVERLAY
        ):
            level = "UNKNOWN"

        # Annotate the preview.
        annotated, box = link.tracker.annotate(
            body,
            level,
        )

        if self._stopping():
            return self.respond(
                503,
                b"Fleet Guardian is shutting down.",
            )

        # Store the frame only if the trip and selection remain valid.
        with fleet.frame_lock:

            if not fleet.preview_is_selected(link.session_id):
                return self.respond(
                    403,
                    b"Camera preview selection has changed.",
                )

            current_trip = fleet.store.assignment(link.vehicle)

            if (
                not current_trip
                or current_trip["id"] != trip["id"]
            ):
                return self.respond(
                    409,
                    b"Vehicle trip changed during preview upload.",
                )

            fleet.frames[link.session_id] = (
                datetime.now(timezone.utc),
                annotated,
                trip["id"],
            )

        payload = json.dumps({
            "box": box,
            "level": level,
        }).encode("utf-8")

        return self.respond(
            200,
            payload,
            "application/json",
        )

    def _handle_prediction(self, link, body):
        """Decode and process a phone prediction."""

        try:
            data = json.loads(body)

        except (json.JSONDecodeError, UnicodeDecodeError):
            raise ValueError(
                "Invalid JSON prediction payload."
            ) from None

        if not isinstance(data, dict):
            raise ValueError(
                "Prediction must be a JSON object."
            )

        result = link.receive_prediction(
            self.server.fleet,
            data,
            self.server.stopping,
        )

        if self._stopping():
            return None

        payload = json.dumps(result).encode("utf-8")

        return self.respond(
            200,
            payload,
            "application/json",
        )
