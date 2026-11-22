
"""Run a temporary Cloudflare Quick Tunnel to the local phone service."""

from contextlib import contextmanager
from pathlib import Path
from queue import Empty, Queue
import re
import shutil
import subprocess
import threading


TUNNEL_START_TIMEOUT = 65
PROCESS_STOP_TIMEOUT = 5

TUNNEL_URL_PATTERN = re.compile(
    r"https://[a-z0-9-]+\.trycloudflare\.com\b",
    re.IGNORECASE,
)


@contextmanager
def trip_proxy(port):
    """Start cloudflared and yield the public Quick Tunnel URL."""

    if (
        isinstance(port, bool)
        or not isinstance(port, int)
        or not 1 <= port <= 65535
    ):
        raise ValueError("Port must be an integer between 1 and 65535.")

    # cloudflare.py is in <project>/fleet/tunnel.
    # The bundled helper is in <project>/tools/cloudflared.exe.
    bundled = (
        Path(__file__).resolve().parents[2]
        / "tools"
        / "cloudflared.exe"
    )

    cli = (
        str(bundled)
        if bundled.is_file()
        else shutil.which("cloudflared")
    )

    if not cli:
        raise SystemExit(
            "cloudflared was not found. Install it with: "
            "winget install --id Cloudflare.cloudflared -e"
        )

    command = [
        cli,
        "tunnel",
        "--no-autoupdate",
        "--protocol",
        "http2",
        "--url",
        f"http://127.0.0.1:{port}",
    ]

    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )

    except OSError as error:
        raise SystemExit(
            f"Could not launch cloudflared: {error}"
        ) from error

    ready = Queue(maxsize=1)

    def notify(result):
        """Send only the first startup result."""
        try:
            ready.put_nowait(result)
        except Exception:
            pass

    def read_output():
        url = None
        registered = False
        notified = False
        last_error = ""

        try:
            if process.stdout is None:
                notify((
                    None,
                    "Could not read cloudflared output.",
                ))
                return

            for line in process.stdout:
                match = TUNNEL_URL_PATTERN.search(line)

                if match:
                    url = match.group(0)

                if "Registered tunnel connection" in line:
                    registered = True

                if url and registered and not notified:
                    notify((url, None))
                    notified = True

                if "ERR" in line.upper():
                    last_error = line.strip()

        except (OSError, ValueError) as error:
            last_error = str(error)

        finally:
            if not notified:
                notify((
                    None,
                    last_error
                    or "cloudflared exited before the tunnel was ready.",
                ))

    reader = threading.Thread(
        target=read_output,
        name="cloudflared-output",
        daemon=True,
    )

    reader.start()

    try:
        print(
            "Starting Cloudflare Quick Tunnel…",
            flush=True,
        )

        try:
            url, error = ready.get(
                timeout=TUNNEL_START_TIMEOUT
            )

        except Empty:
            raise SystemExit(
                "Cloudflare tunnel startup timed out after "
                f"{TUNNEL_START_TIMEOUT} seconds. "
                "Check internet access, firewall rules and "
                "outbound connectivity."
            )

        if not url:
            raise SystemExit(
                f"Could not start Cloudflare Quick Tunnel: {error}"
            )

        if process.poll() is not None:
            raise SystemExit(
                "cloudflared exited immediately after tunnel startup."
            )

        yield url

    finally:
        if process.poll() is None:
            process.terminate()

            try:
                process.wait(timeout=PROCESS_STOP_TIMEOUT)

            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()

        reader.join(timeout=2)

        if process.stdout:
            process.stdout.close()
