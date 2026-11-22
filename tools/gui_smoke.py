
"""Owner GUI smoke check.

Uses temporary data and never modifies the user's fleet database.
Tests the current fleet.manager architecture.
"""

from io import BytesIO
from pathlib import Path
import sys
import tempfile
import threading
import time
import tkinter as tk

from PIL import Image, ImageGrab

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from fleet.manager.network import ApiClient
from fleet.manager.owner_ui import OwnerApp
from fleet.manager.server import FleetServer
from fleet.manager.storage import Store
from fleet.manager.ui_common import enable_high_dpi


def run():
    enable_high_dpi()

    output = PROJECT_ROOT / "build" / "gui-check"
    output.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as directory:
        data = Path(directory)

        store = Store(data / "fleet.sqlite3")
        store.seed()

        server = FleetServer(
            ("127.0.0.1", 0),
            store,
            "owner-smoke",
            "device-smoke",
        )

        server_thread = threading.Thread(
            target=server.serve_forever,
            daemon=True,
        )
        server_thread.start()

        root = None
        owner = None

        try:
            url = f"http://127.0.0.1:{server.server_port}"

            root = tk.Tk()
            errors = []

            root.report_callback_exception = (
                lambda *error: errors.append(error)
            )

            root.geometry("1280x800+10+10")

            owner = OwnerApp(
                root,
                ApiClient(url, "owner-smoke"),
            )

            def pump(seconds):
                end = time.monotonic() + seconds

                while time.monotonic() < end:
                    root.update()
                    time.sleep(0.02)

                assert not errors, errors

            def capture(window, filename):
                window.lift()
                window.update()
                time.sleep(0.25)

                destination = output / filename

                if sys.platform == "win32":
                    import ctypes
                    from ctypes import wintypes

                    get_ancestor = ctypes.windll.user32.GetAncestor
                    get_ancestor.argtypes = [
                        wintypes.HWND,
                        wintypes.UINT,
                    ]
                    get_ancestor.restype = wintypes.HWND

                    handle = get_ancestor(window.winfo_id(), 2)

                    ImageGrab.grab(
                        window=handle
                    ).save(destination)

                else:
                    box = (
                        window.winfo_rootx(),
                        window.winfo_rooty(),
                        window.winfo_rootx() + window.winfo_width(),
                        window.winfo_rooty() + window.winfo_height(),
                    )

                    ImageGrab.grab(
                        bbox=box
                    ).save(destination)

            # ------------------------------------------
            # 1. Dashboard startup
            # ------------------------------------------

            pump(2)

            assert owner.online, "Owner dashboard is offline"

            assert len(owner.table.get_children()) == 3, (
                "Expected three seeded dashboard records"
            )

            capture(root, "owner-overview.png")

            # ------------------------------------------
            # 2. Dashboard pages
            # ------------------------------------------

            for page in (
                "Vehicles",
                "Drivers",
                "Routes",
                "Assignments",
            ):
                owner.show_page(page)
                pump(0.3)

                assert owner.table.get_children(), (
                    f"No records displayed on {page}"
                )

            # ------------------------------------------
            # 3. Entity dialog
            # ------------------------------------------

            owner.entity_dialog("drivers")
            pump(0.3)

            dialogs = [
                window
                for window in root.winfo_children()
                if isinstance(window, tk.Toplevel)
            ]

            assert dialogs, "Entity dialog did not open"

            for window in dialogs:
                window.destroy()

            # ------------------------------------------
            # 4. Assignment dialog
            # ------------------------------------------

            owner.assignment_dialog()
            pump(0.3)

            dialogs = [
                window
                for window in root.winfo_children()
                if isinstance(window, tk.Toplevel)
            ]

            assert dialogs, "Assignment dialog did not open"

            for window in dialogs:
                window.destroy()

            # ------------------------------------------
            # 5. Live monitoring
            # ------------------------------------------

            owner.show_page("Live monitoring")
            owner.choose_vehicle(1)

            pump(0.5)

            assert "Aarav" in owner.monitor_details.cget("text"), (
                "Vehicle/driver details were not displayed"
            )

            image_bytes = BytesIO()

            Image.new(
                "RGB",
                (480, 270),
                "#284662",
            ).save(
                image_bytes,
                format="JPEG",
            )

            owner.render_frame(
                1,
                image_bytes.getvalue(),
            )

            assert owner.video.image is not None, (
                "Video preview was not rendered"
            )

            capture(root, "owner-monitor.png")

            # ------------------------------------------
            # 6. Logs and reports page
            # ------------------------------------------

            owner.show_page("Logs & reports")
            pump(0.5)

            owner.apply_filters()
            pump(0.5)

            capture(root, "owner-logs.png")

            # ------------------------------------------
            # 7. Frame endpoint
            # ------------------------------------------

            response = owner.api.request(
                "/frame/1",
                raw=True,
            )

            # An empty frame is acceptable before a camera
            # uploads an image. If a frame exists, verify JPEG.
            if response:
                assert response.startswith(b"\xff\xd8"), (
                    "Frame endpoint did not return JPEG data"
                )

            # ------------------------------------------
            # 8. Final checks
            # ------------------------------------------

            pump(0.5)

            assert not errors, errors

            print("OWNER GUI SMOKE PASS")
            print("Dashboard startup: PASS")
            print("Dashboard pages: PASS")
            print("Entity dialog: PASS")
            print("Assignment dialog: PASS")
            print("Live monitoring: PASS")
            print("Image rendering: PASS")
            print("Logs page: PASS")
            print("Frame endpoint: PASS")
            print(f"Screenshots: {output}")

        finally:
            if owner is not None:
                owner.stop.set()

            if root is not None:
                try:
                    root.destroy()
                except tk.TclError:
                    pass

            server.shutdown()
            server.server_close()
            server_thread.join(timeout=3)


if __name__ == "__main__":
    run()
