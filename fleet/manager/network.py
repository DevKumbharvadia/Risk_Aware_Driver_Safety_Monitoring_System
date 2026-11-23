
"""Small JSON-over-HTTP client using Python's standard library."""

import json
import math
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import urlsplit


class ApiError(Exception):
    """API communication or response error."""

    def __init__(self, message, status=0):
        super().__init__(message)
        self.status = status


class ApiClient:
    """Authenticated JSON-over-HTTP client."""

    def __init__(self, base_url, token, timeout=5):
        if not isinstance(base_url, str) or not base_url.strip():
            raise ValueError(
                "A valid API base URL is required."
            )

        if not isinstance(token, str) or not token.strip():
            raise ValueError(
                "An API authentication token is required."
            )

        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not math.isfinite(timeout)
            or timeout <= 0
        ):
            raise ValueError(
                "Timeout must be a finite number greater than zero."
            )

        base_url = base_url.strip().rstrip("/")

        parsed_url = urlsplit(base_url)

        if (
            parsed_url.scheme not in ("http", "https")
            or not parsed_url.netloc
            or parsed_url.username is not None
            or parsed_url.password is not None
            or parsed_url.query
            or parsed_url.fragment
        ):
            raise ValueError(
                "API base URL must be a valid HTTP or HTTPS URL."
            )

        self.base_url = base_url
        self.token = token.strip()
        self.timeout = float(timeout)

    @staticmethod
    def _validate_path(path):
        """Validate a relative API endpoint path."""

        if (
            not isinstance(path, str)
            or not path.startswith("/")
            or path.startswith("//")
            or "\\" in path
            or "\r" in path
            or "\n" in path
        ):
            raise ApiError(
                "Invalid API path."
            )

        parsed_path = urlsplit(path)

        if (
            parsed_path.scheme
            or parsed_path.netloc
            or parsed_path.fragment
        ):
            raise ApiError(
                "Invalid API path."
            )

        return path

    @staticmethod
    def _error_message(content, fallback):
        """Extract a readable message from an HTTP error response."""

        if not content:
            return str(fallback)

        try:
            payload = json.loads(content)

            if isinstance(payload, dict):
                message = (
                    payload.get("error")
                    or payload.get("message")
                    or fallback
                )

                if isinstance(message, str):
                    return message

            return str(fallback)

        except (ValueError, UnicodeError):
            message = content.strip()

            return message if message else str(fallback)

    def request(self, path, data=None, raw=False):
        """Send an authenticated GET or POST request."""

        path = self._validate_path(path)

        if not isinstance(raw, bool):
            raise ApiError(
                "The raw argument must be a boolean."
            )

        # Encode request data.
        try:
            body = (
                json.dumps(
                    data,
                    allow_nan=False,
                    ensure_ascii=False,
                ).encode("utf-8")
                if data is not None
                else None
            )

        except (TypeError, ValueError, OverflowError) as error:
            raise ApiError(
                f"Invalid request data: {error}"
            ) from error

        request = Request(
            self.base_url + path,
            data=body,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": (
                    "*/*" if raw
                    else "application/json"
                ),
                **(
                    {"Content-Type": "application/json"}
                    if body is not None
                    else {}
                ),
            },
            method="POST" if body is not None else "GET",
        )

        try:
            with urlopen(
                request,
                timeout=self.timeout,
            ) as response:

                content = response.read()

                if raw:
                    return content

                if not content:
                    return None

                try:
                    return json.loads(
                        content.decode("utf-8-sig")
                    )

                except (ValueError, UnicodeError) as error:
                    raise ApiError(
                        "Server returned an invalid JSON response.",
                        response.status,
                    ) from error

        except HTTPError as error:
            try:
                content = error.read().decode(
                    "utf-8",
                    errors="replace",
                )

                message = self._error_message(
                    content,
                    error.reason,
                )

            except OSError:
                message = str(error.reason)

            raise ApiError(
                str(message),
                error.code,
            ) from error

        except (URLError, TimeoutError, OSError) as error:
            raise ApiError(
                f"Server unavailable: {error}"
            ) from error

        except ValueError as error:
            raise ApiError(
                f"Invalid server response: {error}"
            ) from error
