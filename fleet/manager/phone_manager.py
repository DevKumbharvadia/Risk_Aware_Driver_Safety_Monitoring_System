
"""Start and manage the Fleet Guardian phone-camera service."""

from http.server import ThreadingHTTPServer
import logging
import secrets
import threading
import tkinter as tk
import uuid

from .network import ApiClient
from .owner.owner_ui import OwnerApp
from .server import FleetServer
from .storage import Store
from ..tunnel.cloudflare import trip_proxy

from .mobile_assets import validate_mobile_assets
from .mobile_config import (
    PROJECT_ROOT,
    MOBILE_ROOT,
    MOBILE_PAGE,
    MOBILE_CSS,
    MOBILE_JS,
    MOBILE_MODEL,
    MAX_PREDICTION_BYTES,
    MAX_PREVIEW_BYTES,
    PREDICTION_MAX_AGE,
    PREDICTION_FUTURE_TOLERANCE,
    PREDICTION_STALE_OVERLAY,
)
from .mobile_processing import (
    behavior_label,
    classifier_summary,
    PreviewTracker,
    apply_vehicle_speed,
)
from .vehicle_link import VehicleLink
from .mobile_handler import MobileHandler


def run_manager(args, config):
    """Start Fleet Guardian with Cloudflare Quick Tunnel."""

    logging.info("Fleet Guardian starting in Cloudflare Quick Tunnel mode.")
    validate_mobile_assets()

    store = Store(args.data_dir / "fleet.sqlite3")
    store.seed()

    fleet = FleetServer(
        ("127.0.0.1", 0),
        store,
        config["owner_token"],
        config["device_token"],
    )

    mobile_server = ThreadingHTTPServer(
        ("127.0.0.1", 0),
        MobileHandler,
    )
    mobile_server.daemon_threads = False
    mobile_server.block_on_close = True
    mobile_server.stopping = threading.Event()
    mobile_server.fleet = fleet
    mobile_server.links = {}
    mobile_server.links_lock = threading.Lock()

    fleet.mobile_sessions = {}
    fleet.mobile_sessions_lock = threading.Lock()

    primary_sessions = {}
    sessions_lock = threading.Lock()

    with (
        fleet,
        mobile_server,
        trip_proxy(mobile_server.server_port) as base_url,
    ):
        logging.info("Cloudflare phone service ready at %s", base_url)

        print("\n" + "=" * 68, flush=True)
        print("FLEET GUARDIAN — CLOUDFLARE QUICK TUNNEL READY", flush=True)
        print(f"Public phone service: {base_url}", flush=True)
        print("Browser-side ONNX inference enabled.", flush=True)
        print(
            "Each phone connection now has an independent camera session.",
            flush=True,
        )
        print("=" * 68 + "\n", flush=True)

        def create_phone_link(vehicle_id):
            """Create a separate authenticated session for a phone."""

            try:
                vehicle_id = int(vehicle_id)
            except (TypeError, ValueError):
                raise ValueError("Invalid vehicle ID") from None

            session_id = uuid.uuid4().hex
            token = secrets.token_urlsafe(32)

            link = VehicleLink(vehicle_id, session_id)
            link.url = f"{base_url}/#{token}"

            with mobile_server.links_lock:
                mobile_server.links[token] = link

            with fleet.mobile_sessions_lock:
                fleet.mobile_sessions[session_id] = link

            logging.info(
                "Created phone session %s for vehicle %s",
                session_id,
                vehicle_id,
            )

            return link.url

        def get_phone_link(vehicle_id):
            """Return the stable primary phone link for a vehicle."""

            try:
                vehicle_id = int(vehicle_id)
            except (TypeError, ValueError):
                raise ValueError("Invalid vehicle ID") from None

            with sessions_lock:
                existing = primary_sessions.get(vehicle_id)

                if existing:
                    return existing

                link = create_phone_link(vehicle_id)
                primary_sessions[vehicle_id] = link
                return link

        def list_phone_sessions(vehicle_id=None):
            """Return session details for the owner dashboard."""

            now = __import__("time").monotonic()
            result = []

            with fleet.mobile_sessions_lock:
                sessions = list(fleet.mobile_sessions.values())

            for link in sessions:
                if (
                    vehicle_id is not None
                    and link.vehicle != int(vehicle_id)
                ):
                    continue

                result.append({
                    "session_id": link.session_id,
                    "vehicle_id": link.vehicle,
                    "created_at": link.created_at,
                    "last_seen_seconds": max(0.0, now - link.last_seen),
                    "link": link.url,
                })

            return result

        mobile_thread = threading.Thread(
            target=mobile_server.serve_forever,
            name="fleet-mobile-http",
            daemon=True,
        )
        fleet_thread = threading.Thread(
            target=fleet.serve_forever,
            name="fleet-owner-http",
            daemon=True,
        )

        mobile_thread.start()
        fleet_thread.start()

        root = tk.Tk()

        OwnerApp(
            root,
            ApiClient(
                f"http://127.0.0.1:{fleet.server_port}",
                config["owner_token"],
            ),
            public_url=base_url,
            phone_link_provider=get_phone_link,
            create_phone_link_provider=create_phone_link,
            phone_sessions_provider=list_phone_sessions,
        )

        shutdown_lock = threading.Lock()
        shutdown_started = False

        def shutdown():
            nonlocal shutdown_started

            with shutdown_lock:
                if shutdown_started:
                    return
                shutdown_started = True

            logging.info("Fleet Guardian shutdown requested.")

            fleet.select_preview(None)
            mobile_server.stopping.set()

            mobile_server.shutdown()
            fleet.shutdown()

            try:
                if root.winfo_exists():
                    root.destroy()
            except tk.TclError:
                pass

        root.protocol("WM_DELETE_WINDOW", shutdown)

        logging.info(
            "Fleet Guardian ready; waiting for owner dashboard and phones."
        )

        try:
            root.mainloop()
        finally:
            shutdown()
