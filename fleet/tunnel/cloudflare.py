"""Run a temporary public HTTPS tunnel to the driver's loopback service."""
from contextlib import contextmanager
from pathlib import Path
from queue import Empty, Queue
import re
import shutil
import subprocess
import threading


@contextmanager
def trip_proxy(port):
    bundled = Path(__file__).resolve().parents[1] / "tools" / "cloudflared.exe"
    cli = str(bundled) if bundled.is_file() else shutil.which("cloudflared")
    if not cli:
        raise SystemExit("Install the PC helper with: winget install --id Cloudflare.cloudflared -e")
    process = subprocess.Popen([cli, "tunnel", "--no-autoupdate", "--protocol", "http2", "--url", f"http://127.0.0.1:{port}"],
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                               encoding="utf-8", errors="replace")
    ready = Queue()

    def read_output():
        url = None
        last_error = ""
        for line in process.stdout:
            match = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com\b", line)
            if match:
                url = match.group()
            if url and "Registered tunnel connection" in line:
                ready.put((url, None))
            if "ERR" in line:
                last_error = line.strip()
        ready.put((None, last_error or "The tunnel helper exited."))

    reader = threading.Thread(target=read_output, daemon=True)
    reader.start()
    try:
        print("Connecting the phone service to Cloudflare…", flush=True)
        try:
            url, error = ready.get(timeout=65)
        except Empty:
            raise SystemExit("Tunnel connection timed out. Check internet access and outbound port 7844, then retry.")
        if not url:
            raise SystemExit(f"Could not start Trip Fleet: {error}")
        yield url
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        reader.join(timeout=2)
        process.stdout.close()
