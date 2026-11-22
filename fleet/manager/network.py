"""Small JSON-over-HTTP client using Python's standard library."""
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class ApiError(Exception):
    def __init__(self, message, status=0):
        super().__init__(message)
        self.status = status


class ApiClient:
    def __init__(self, base_url, token):
        self.base_url = base_url.rstrip("/")
        self.token = token

    def request(self, path, data=None, raw=False):
        body = json.dumps(data).encode("utf-8") if data is not None else None
        request = Request(self.base_url + path, data=body, headers={
            "Authorization": "Bearer " + self.token, "Content-Type": "application/json"})
        try:
            with urlopen(request, timeout=3) as response:
                content = response.read()
                return content if raw else json.loads(content)
        except HTTPError as error:
            try:
                message = json.loads(error.read()).get("error", str(error))
            except (ValueError, UnicodeError):
                message = str(error)
            raise ApiError(message, error.code) from error
        except (URLError, TimeoutError, OSError) as error:
            raise ApiError("Server unavailable: " + str(error)) from error
