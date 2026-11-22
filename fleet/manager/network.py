
"""Small JSON-over-HTTP client using Python's standard library."""

import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class ApiError(Exception):
    """API communication or response error."""

    def __init__(self, message, status=0):
        super().__init__(message)
        self.status = status


class ApiClient:
    """Authenticated JSON-over-HTTP client."""

    def __init__(self, base_url, token, timeout=5):
        if not isinstance(base_url, str) or not base_url.strip():
            raise ValueError("A valid API base URL is required.")

        if not isinstance(token, str) or not token.strip():
            raise ValueError("An API authentication token is required.")

        if timeout <= 0:
            raise ValueError("Timeout must be greater than zero.")

        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def request(self, path, data=None, raw=False):
        """Send an authenticated GET or POST request."""

        if not isinstance(path, str) or not path.startswith("/") or path.startswith("//"):
            raise ApiError("Invalid API path.")

        try:
            body = json.dumps(data).encode("utf-8") if data is not None else None
        except (TypeError, ValueError) as error:
            raise ApiError(f"Invalid request data: {error}") from error

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
            with urlopen(request, timeout=self.timeout) as response:
                content = response.read()

                if raw:
                    return content

                if not content:
                    return None

                try:
                    return json.loads(content.decode("utf-8-sig"))
                except (ValueError, UnicodeError) as error:
                    raise ApiError(
                        "Server returned an invalid JSON response.",
                        response.status,
                    ) from error

        except HTTPError as error:
            try:
                content = error.read().decode("utf-8", errors="replace")

                try:
                    payload = json.loads(content)
                    message = (
                        payload.get("error", payload.get("message", error.reason))
                        if isinstance(payload, dict)
                        else error.reason
                    )
                except ValueError:
                    message = content.strip() or error.reason

            except OSError:
                message = error.reason

            raise ApiError(str(message), error.code) from error

        except (URLError, TimeoutError, OSError) as error:
            raise ApiError(f"Server unavailable: {error}") from error
