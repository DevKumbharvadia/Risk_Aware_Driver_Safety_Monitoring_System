"""Phone-camera fleet manager: owner dashboard plus an HTTPS phone sensor terminal.

One manager PC runs the dashboard and serves each vehicle a private phone link.
A driver opens the link in Chrome; the phone streams JPEG frames and GPS, and the
PC runs the classifier, risk rules and storage. With --trip the phone service is
exposed over a temporary Cloudflare HTTPS tunnel instead of the trusted LAN.
"""
import base64
from contextlib import ExitStack
from datetime import datetime, timezone
import json
import logging
import math
from pathlib import Path
import secrets
import socket
import ssl
import subprocess
import sys
import threading
import time
import uuid
import webbrowser
import tkinter as tk
from tkinter import ttk
from http.server import ThreadingHTTPServer
from urllib.parse import urlsplit

from .network import ApiClient
from ..perception.face_preview import FacePreview, behavior_label, classifier_summary
from ..perception.face_activity import FaceActivity
from .owner_ui import OwnerApp
from ..mobile.phone_speed import PhoneHandler, PhoneSpeed
from ..risk.engine import Measurements, RiskEngine
from .server import FleetServer
from .storage import Store, utc_now

TOOLS_DIR = Path(__file__).resolve().parents[2] / "tools"
MOBILE_PAGE = Path(__file__).resolve().parents[1] / "mobile" / "mobile.html"


def apply_vehicle_speed(readings, data):
    gps = PhoneSpeed()
    fix = {}
    if data.get("gps"):
        try:
            fix = data["gps"]
            gps_age = data["captured"] - fix["timestamp"]
            gps.accept({**fix, "timestamp": time.time() - gps_age - max(0, time.monotonic() - data["server_capture"])})
        except ValueError:
            pass  # An old fix is equivalent to missing speed.
    gps.apply(readings)
    missing = readings.assessment_note.startswith(("Phone GPS", "Waiting for phone GPS"))
    readings.speed_method = "unavailable" if missing else ("GPS estimate" if fix.get("estimated") else "GPS")
    if missing:
        messages = {"denied": "Allow precise location for this site in the phone browser.",
                    "timeout": "GPS timed out. Try outdoors with precise location enabled.",
                    "unavailable": "Location unavailable. Check phone location settings.",
                    "estimating": "Waiting for sufficiently accurate movement to estimate speed."}
        readings.assessment_note = messages.get(data.get("gps_status"), readings.assessment_note)


class VehicleLink:
    def __init__(self, vehicle):
        self.vehicle = vehicle
        self.lock = threading.Lock()
        self.engine = RiskEngine()
        self.trip_id = None
        self.previous = 0
        self.tracker = FacePreview()
        self.face_activity = None
        self.overlay = (None, 0, "UNKNOWN")

    def receive(self, fleet, data):
        with self.lock:
            trip = fleet.store.assignment(self.vehicle)
            if not trip:
                raise ValueError("Ask the manager to assign this vehicle first.")
            now = time.monotonic()
            age = now - data["server_capture"]
            if not math.isfinite(age) or not -1 <= age <= 5:
                raise ValueError("Delayed frame. Reconnecting to the manager…")
            frame = base64.b64decode(data["jpeg"], validate=True)
            readings = fleet.classify(frame)
            if self.face_activity is None:
                self.face_activity = FaceActivity()
            if self.trip_id != trip["id"]:
                self.face_activity.reset_mount()
            calibration = data.get("calibrate")
            if isinstance(calibration, str) and 0 < len(calibration) <= 64 and calibration != self.face_activity.calibration_id:
                self.face_activity.start_calibration(calibration)
                self.engine = RiskEngine()
                self.previous = 0
            self.face_activity.observe(frame, readings)
            if time.monotonic() - data["server_capture"] > 5:
                raise ValueError("Processing took too long. Waiting for the next frame.")
            apply_vehicle_speed(readings, data)
            readings.accelerometer = data.get("accelerometer")
            readings.gyroscope = data.get("gyroscope")
            readings = Measurements.from_dict(readings.to_dict())
            gap = now - self.previous
            if trip["id"] != self.trip_id or gap > 3:
                self.engine = RiskEngine()
                gap = 0
            self.trip_id = trip["id"]
            self.previous = now
            risk = self.engine.update(readings, gap)
            self.overlay = (trip["id"], time.monotonic(), risk.level)
            fleet.store.add_sample({"id": str(uuid.uuid4()), "vehicle_id": self.vehicle,
                "trip_id": trip["id"], "captured_at": utc_now(), "readings": readings.to_dict(),
                "risk": risk.to_dict()})
            if not data.get("separate_preview"):
                with fleet.frame_lock:
                    fleet.frames[self.vehicle] = (datetime.now(timezone.utc), frame, trip["id"])
            return {"driver": trip["driver_name"], "route": trip["route_name"],
                    "mount_note": self.face_activity.mount_note,
                    "calibration_id": self.face_activity.calibration_id,
                    "label": behavior_label(readings.behavior, readings.confidence, readings.face_activity, readings.handset_visible),
                    "behavior": readings.behavior, "confidence": readings.confidence,
                    "raw_label": readings.classifier_label, "raw_score": readings.classifier_score,
                    "prediction": classifier_summary(readings.classifier_label, readings.classifier_score, readings.handset_visible),
                    "handset": readings.handset_visible,
                    "risk": risk.level, "reason": risk.reason,
                    "trip_id": trip["id"], "speed_method": readings.speed_method,
                    "speed": None if readings.speed_method == "unavailable" else readings.speed}


class MobileHandler(PhoneHandler):
    def do_GET(self):
        if self.path == "/version":
            return self.respond(200, b'{"mobile":6}', "application/json")
        if self.path == "/clock":
            return self.respond(200, json.dumps(time.monotonic()).encode(), "application/json")
        if urlsplit(self.path).path != "/":
            return self.respond(404, b"Unknown page")
        self.respond(200, MOBILE_PAGE.read_bytes(), "text/html; charset=utf-8")

    def do_POST(self):
        try:
            if self.path not in ("/sample", "/preview"):
                return self.respond(404, b"Unknown endpoint")
            link = self.server.links.get(self.headers.get("Authorization", "").removeprefix("Bearer "))
            if not link:
                return self.respond(403, b"Open the current vehicle link from the manager PC.")
            size = int(self.headers.get("Content-Length", 0))
            if not 0 < size <= 400000:
                raise ValueError("Invalid sample size")
            body = self.rfile.read(size)
            if self.path == "/preview":
                fleet = self.server.fleet
                trip = fleet.store.assignment(link.vehicle)
                if not trip or str(trip["id"]) != self.headers.get("X-Trip"):
                    raise ValueError("Trip changed")
                if size > 250000 or not body.startswith(b"\xff\xd8") or not body.endswith(b"\xff\xd9"):
                    raise ValueError("Invalid JPEG preview")
                assessed_trip, assessed_at, level = link.overlay
                if assessed_trip != trip["id"] or time.monotonic()-assessed_at > 2.5:
                    level = "UNKNOWN"
                annotated, box = link.tracker.annotate(body, level)
                with fleet.frame_lock:
                    fleet.frames[link.vehicle] = (datetime.now(timezone.utc), annotated, trip["id"])
                return self.respond(200, json.dumps({"box":box,"level":level}).encode(), "application/json")
            result = link.receive(self.server.fleet, json.loads(body))
            self.respond(200, json.dumps(result).encode(), "application/json")
        except (ValueError, KeyError, TypeError, OSError) as error:
            logging.warning("Phone sample rejected: %s", error)
            self.respond(400, str(error).encode())
        except Exception:
            logging.exception("Phone sample failed")
            self.respond(500, b"Model or fleet service unavailable. Check PC setup.")


def run_manager(args, config):
    """Start the owner dashboard and the phone sensor terminal for every vehicle."""
    data = args.data_dir
    remote = args.trip
    if remote:
        from ..tunnel.cloudflare import trip_proxy
        address = "127.0.0.1"
    else:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("192.0.2.1", 9))
            address = probe.getsockname()[0]
    logging.info("Fleet manager starting (trip=%s) on %s", remote, address)
    certs = data / ("phone-link-" + address)
    if not remote and not (certs/"server.crt").exists():
        subprocess.run([sys.executable, str(TOOLS_DIR / "create_gps_certificate.py"),
                        address, "--output", str(certs)], check=True)
    store = Store(data / "fleet.sqlite3")
    store.seed()
    fleet = FleetServer(("127.0.0.1", 0), store, config["owner_token"], config["device_token"])
    with fleet, ThreadingHTTPServer((address, 0 if remote else 8766), MobileHandler) as mobile, ExitStack() as stack:
        if remote:
            base_url = stack.enter_context(trip_proxy(mobile.server_port))
        else:
            base_url = f"https://{address}:8766"
            tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            tls.load_cert_chain(certs/"server.crt", certs/"server.key")
            mobile.socket = tls.wrap_socket(mobile.socket, server_side=True)
        logging.info("Phone terminal ready at %s", base_url)
        mobile.fleet = fleet
        mobile.links = {}
        threading.Thread(target=fleet.serve_forever, daemon=True).start()
        threading.Thread(target=mobile.serve_forever, daemon=True).start()
        root = tk.Tk()
        OwnerApp(root, ApiClient(f"http://127.0.0.1:{fleet.server_port}", config["owner_token"]))
        pairing = tk.Toplevel(root)
        pairing.title("Connect a driver phone")
        if remote:
            ttk.Label(pairing, text="Send the vehicle link to its driver. Open it in Chrome over mobile data.").pack(padx=12,pady=8)
        else:
            ttk.Label(pairing, text="First use: copy phone-ca.crt to your phone and install it as a CA certificate.").pack(padx=12,pady=8)
            ttk.Button(pairing, text="Open certificate folder", command=lambda: webbrowser.open(certs.as_uri())).pack()
        table = ttk.Frame(pairing)
        table.pack(fill="both", padx=12,pady=8)
        tokens = {}
        def refresh():
            for child in table.winfo_children():
                child.destroy()
            for vehicle in store.snapshot()["vehicles"]:
                vehicle_id = vehicle["id"]
                if vehicle_id not in tokens:
                    token = secrets.token_urlsafe(20)
                    tokens[vehicle_id] = token
                    mobile.links[token] = VehicleLink(vehicle_id)
                url = f"{base_url}/#{tokens[vehicle_id]}"
                row = ttk.Frame(table)
                row.pack(fill="x")
                ttk.Label(row, text=vehicle["registration"], width=18).pack(side="left")
                def copy(value=url):
                    root.clipboard_clear()
                    root.clipboard_append(value)
                ttk.Button(row, text="Copy phone link", command=copy).pack(side="left")
        refresh()
        ttk.Button(pairing, text="Refresh vehicle list", command=refresh).pack(pady=6)
        pairing.protocol("WM_DELETE_WINDOW", pairing.iconify)
        logging.info("Fleet manager ready; waiting for owner dashboard and phones")
        try:
            root.mainloop()
        finally:
            mobile.shutdown()
            fleet.shutdown()
