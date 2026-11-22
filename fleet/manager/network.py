
"""Small JSON-over-HTTP client using Python's standard library."""

import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class ApiError(Exception):
    """Represents an API communication or response error."""

    def __init__(self, message, status=0):
        super().__init__(message)
        self.status = status


class ApiClient:
    """Authenticated JSON-over-HTTP client."""

    def __init__(self, base_url, token):
        self.base_url = base_url.rstrip("/")
        self.token = token

    def request(self, path, data=None, raw=False):
        """Send an authenticated HTTP request.

        Args:
            path: API endpoint path.
            data: Optional JSON-serializable request payload.
            raw: Return response bytes instead of decoding JSON.

        Returns:
            Decoded JSON data or raw response bytes.

        Raises:
            ApiError: If communication or response processing fails.
        """

        if not isinstance(path, str) or not path.startswith("/"):
            raise ApiError("API path must start with '/'.")

        body = (
            json.dumps(data).encode("utf-8")
            if data is not None
            else None
        )

        request = Request(
            self.base_url + path,
            data=body,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST" if body is not None else "GET",
        )

        try:
            with urlopen(request, timeout=5) as response:
                content = response.read()

                if raw:
                    return content

                if not content:
                    return None

                try:
                    return json.loads(content.decode("utf-8"))

                except (ValueError, UnicodeError) as error:
                    raise ApiError(
                        "Server returned an invalid JSON response.",
                        response.status,
                    ) from error

        except HTTPError as error:
            try:
                error_body = error.read().decode("utf-8")
                payload = json.loads(error_body)

                if isinstance(payload, dict):
                    message = payload.get("error", error.reason)
                else:
                    message = error.reason

            except (ValueError, UnicodeError, OSError):
                message = error.reason

            raise ApiError(
                str(message),
                error.code,
            ) from error

        except (URLError, TimeoutError, OSError) as error:
            raise ApiError(
                f"Server unavailable: {error}"
            ) from error
