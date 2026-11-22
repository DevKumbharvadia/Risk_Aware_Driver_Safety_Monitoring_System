
"""Dashboard and camera preview."""

from io import BytesIO
import tkinter as tk
from tkinter import ttk

from ..ui_common import COLORS, fill_table, make_table, vehicle_status


def live_status(state, readings):
    if state == "UNKNOWN":
        return (
            "Camera only"
            if readings.get("source") == "trained_model"
            and readings.get("speed_method") == "unavailable"
            else "Awaiting assessment"
        )
    return "Stopped" if state == "LOW" and readings.get("speed") == 0 else state


class DashboardPageMixin:

    def build_dashboard(self):
        self.metrics = ttk.Label(self.content, style="Metric.TLabel")
        self.metrics.pack(anchor="w", pady=(0, 12))

        split = ttk.Panedwindow(self.content, orient="horizontal")
        split.pack(fill="both", expand=True)

        left = ttk.Frame(split, padding=(0, 0, 10, 0))
        right = ttk.Frame(split, padding=(10, 0, 0, 0))
        split.add(left, weight=3)
        split.add(right, weight=2)

        ttk.Label(left, text="Vehicles", style="Metric.TLabel").pack(anchor="w")
        ttk.Label(
            left,
            text="Select a vehicle to view its live camera and readings.",
            style="Subtitle.TLabel",
        ).pack(anchor="w", pady=(2, 6))

        self.tables["dashboard_vehicles"] = make_table(
            left,
            ("vehicle", "driver", "route", "status", "score"),
            [115, 130, 120, 115, 65],
            height=12,
        )
        self.tables["dashboard_vehicles"].bind(
            "<<TreeviewSelect>>", self.dashboard_vehicle_selected
        )

        self.monitor_heading = ttk.Label(
            right, text="Live vehicle view", style="Metric.TLabel"
        )
        self.monitor_heading.pack(anchor="w")

        self.monitor_details = ttk.Label(
            right,
            text="Choose a vehicle from the list.",
            justify="left",
            wraplength=430,
        )
        self.monitor_details.pack(anchor="w", pady=(6, 8))

        session_row = ttk.Frame(right)
        session_row.pack(fill="x", pady=(0, 8))
        ttk.Label(session_row, text="Camera phone:").pack(side="left")

        self.monitor_session_var = tk.StringVar()
        self.monitor_session_combo = ttk.Combobox(
            session_row,
            textvariable=self.monitor_session_var,
            state="readonly",
            width=24,
        )
        self.monitor_session_combo.pack(side="left", padx=(8, 0))
        self.monitor_session_combo.bind(
            "<<ComboboxSelected>>", self.dashboard_session_selected
        )

        video_area = tk.Frame(right, bg="#14283f", height=270)
        video_area.pack(fill="both", expand=True)

        self.video = tk.Label(
            video_area,
            text="Waiting for camera…",
            bg="#14283f",
            fg="#dbeafe",
            font=("Segoe UI", 12),
            wraplength=420,
        )
        self.video.place(relx=0, rely=0, relwidth=1, relheight=1)

        ttk.Label(
            self.content, text="Recent risk alerts", style="Metric.TLabel"
        ).pack(anchor="w", pady=(12, 4))

        self.tables["dashboard_logs"] = make_table(
            self.content,
            ("time", "vehicle", "driver", "risk", "reason"),
            [145, 110, 130, 85, 420],
            height=4,
        )

    def clear_video(self, message):
        self.video.configure(image="", text=message)
        self.video.image = None

    def dashboard_vehicle_selected(self, _event=None):
        selected = self.tables["dashboard_vehicles"].selection()
        if not selected:
            return

        try:
            vehicle_id = int(selected[0])
        except (ValueError, TypeError):
            return

        with self.selection_lock:
            self.monitor_id = vehicle_id
            self.monitor_session_id = None
            self.latest_preview = None

        self.clear_video("Waiting for selected phone camera…")
        self.update_monitor_sessions()
        self.render_monitor()

    def update_monitor_sessions(self):
        if self.page != "Dashboard":
            return

        if self.monitor_id is None:
            self.monitor_session_combo.configure(values=())
            self.monitor_session_var.set("")

            with self.selection_lock:
                self.monitor_session_id = None
                self.latest_preview = None
            return

        self.refresh_phone_session_cache()

        mapping = {}
        sessions = self.sessions_for_vehicle(self.monitor_id)

        for index, session in enumerate(sessions, 1):
            session_id = self.session_id_of(session)
            if session_id is not None:
                mapping[f"Phone {index}"] = str(session_id)

        self.session_labels = mapping
        values = list(mapping)
        self.monitor_session_combo.configure(values=values)

        with self.selection_lock:
            current = self.monitor_session_id

            if current not in mapping.values():
                current = mapping[values[0]] if values else None

            self.monitor_session_id = current
            self.latest_preview = None

        label = next(
            (name for name, sid in mapping.items() if sid == current),
            "",
        )
        self.monitor_session_var.set(label)

    def dashboard_session_selected(self, _event=None):
        session_id = self.session_labels.get(
            self.monitor_session_var.get()
        )

        with self.selection_lock:
            self.monitor_session_id = session_id
            self.latest_preview = None

        self.clear_video(
            "Waiting for selected phone camera…"
            if session_id else
            "No phone session is available for this vehicle."
        )

    def render_monitor(self):
        if self.page != "Dashboard":
            return

        vehicle = next(
            (v for v in self.data["vehicles"] if v["id"] == self.monitor_id),
            None,
        )

        if not vehicle:
            self.monitor_heading.configure(text="Live vehicle view")
            self.monitor_details.configure(
                text="Choose a vehicle from the list."
            )
            return

        trip = vehicle.get("trip") or {}
        sample = vehicle.get("sample") or {}
        readings = sample.get("readings") or {}

        state = vehicle_status(vehicle) if self.online else "OFFLINE"
        camera = readings.get("source") == "trained_model"

        missing_speed = (
            readings.get("speed_method") == "unavailable"
            or str(readings.get("assessment_note", "")).startswith(
                ("Waiting for phone GPS", "Phone GPS")
            )
        )

        speed = (
            "Unavailable"
            if missing_speed
            else f'{readings.get("speed", "—")} km/h'
        )

        if readings.get("speed_method") == "GPS estimate":
            speed += " (estimated)"

        display_state = (
            "Monitoring"
            if camera and state == "UNKNOWN"
            else live_status(state, readings)
        )

        self.monitor_heading.configure(
            text=f'{vehicle["registration"]}  •  {display_state}',
            foreground=COLORS.get(state, "#15283f"),
        )

        details = [
            f'Driver: {trip.get("driver_name", "Unassigned")}',
            f'Route: {trip.get("route_name", "No route")}',
            f'Behavior: {readings.get("behavior", "—")}',
            f'Speed: {speed}',
            f'Risk: {state}',
        ]

        if sample and state in ("CAUTION", "HIGH"):
            details.append(f'Alert: {sample.get("reason", "")}')

        self.monitor_details.configure(text="\n".join(details))

        if state == "OFFLINE":
            self.clear_video("Device or server offline.")

    def render_frame(self, session_id, frame):
        if (
            self.page != "Dashboard"
            or str(self.monitor_session_id) != str(session_id)
        ):
            return

        try:
            from PIL import Image, ImageTk

            image = Image.open(BytesIO(frame))
            image.thumbnail((
                max(1, self.video.winfo_width() - 8),
                max(1, self.video.winfo_height() - 8),
            ))

            photo = ImageTk.PhotoImage(image)
            self.video.configure(image=photo, text="")
            self.video.image = photo

        except ImportError:
            self.clear_video("Install Pillow to display camera frames.")

        except (OSError, ValueError):
            self.clear_video("Could not decode camera frame.")

    def render_dashboard(self):
        vehicles = self.data["vehicles"]
        statuses = [
            vehicle_status(v) if self.online else "OFFLINE"
            for v in vehicles
        ]

        active = sum(bool(v.get("trip")) for v in vehicles)
        online = sum(
            status in ("LOW", "CAUTION", "HIGH", "UNKNOWN")
            for status in statuses
        )

        self.metrics.configure(
            text=(
                f"{len(vehicles)} vehicles     {active} active trips     "
                f"{online} online     {statuses.count('HIGH')} high risk     "
                f"{statuses.count('CAUTION')} caution"
            )
        )

        rows = [
            (
                vehicle["id"],
                (
                    vehicle["registration"],
                    (vehicle.get("trip") or {}).get("driver_name", "—"),
                    (vehicle.get("trip") or {}).get("route_name", "—"),
                    status,
                    (vehicle.get("sample") or {}).get("score", "—")
                    if status != "OFFLINE" else "—",
                ),
                (status,),
            )
            for vehicle, status in zip(vehicles, statuses)
        ]

        fill_table(self.tables["dashboard_vehicles"], rows)

        if self.monitor_id is None and vehicles:
            self.monitor_id = vehicles[0]["id"]
            self.tables["dashboard_vehicles"].selection_set(
                str(self.monitor_id)
            )
            self.update_monitor_sessions()

        self.render_monitor()
        self.render_dashboard_logs()

    def render_dashboard_logs(self):
        if "dashboard_logs" not in self.tables:
            return

        rows = [
            (
                entry["id"],
                (
                    self.local_time(entry["captured_at"]),
                    entry["vehicle_name"],
                    entry["driver_name"],
                    entry["level"],
                    entry["reason"],
                ),
                (entry["level"],),
            )
            for entry in self.logs[:8]
        ]

        fill_table(self.tables["dashboard_logs"], rows)

    @staticmethod
    def local_time(value):
        from ..ui_common import local_time
        return local_time(value)
