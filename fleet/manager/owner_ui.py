
"""Compact three-page Fleet Guardian owner dashboard."""
import csv
from datetime import datetime, time, timezone
from io import BytesIO
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from urllib.parse import urlencode

from .network import ApiError
from .ui_common import (
    COLORS, fill_table, local_time, make_table,
    setup_style, vehicle_status,
)


ENTITY_FIELDS = {
    "vehicles": ("registration", "model"),
    "drivers": ("name", "license", "phone"),
    "routes": ("name", "origin", "destination"),
}

ENTITY_NAMES = {
    "vehicles": "vehicle",
    "drivers": "driver",
    "routes": "route",
}


def live_status(state, readings):
    if state == "UNKNOWN":
        if (
            readings.get("source") == "trained_model"
            and readings.get("speed_method") == "unavailable"
        ):
            return "Camera only"
        return "Awaiting assessment"

    if state == "LOW" and readings.get("speed") == 0:
        return "Stopped"

    return state


class OwnerApp:
    """Owner dashboard. All Tkinter updates happen on the UI thread."""

    def __init__(self, root, api):
        self.root = root
        self.api = api

        self.data = {
            key: [] for key in (
                "vehicles", "drivers", "routes", "trips"
            )
        }
        self.logs = []
        self.events = queue.Queue()
        self.commands = queue.Queue()
        self.stop = threading.Event()
        self.selection_lock = threading.Lock()

        self.monitor_id = None
        self.latest_preview = None
        self.log_query = ""
        self.page = "Dashboard"
        self.online = False
        self.tables = {}
        self.filters = {}

        root.title("Fleet Guardian")
        root.geometry("1260x790")
        root.minsize(980, 640)
        setup_style(root)

        self.build_shell()
        self.show_page("Dashboard")
        root.protocol("WM_DELETE_WINDOW", self.close)

        threading.Thread(
            target=self.worker,
            name="fleet-api-worker",
            daemon=True,
        ).start()

        threading.Thread(
            target=self.preview_worker,
            name="fleet-preview-worker",
            daemon=True,
        ).start()

        root.after(100, self.drain_events)

    # ---------------------------------------------------------
    # Layout and navigation
    # ---------------------------------------------------------

    def build_shell(self):
        header = tk.Frame(self.root, bg="#14283f", height=76)
        header.pack(fill="x")
        header.pack_propagate(False)

        tk.Label(
            header,
            text="FLEET GUARDIAN",
            bg="#14283f",
            fg="white",
            font=("Segoe UI", 18, "bold"),
        ).pack(side="left", padx=24)

        self.connection = tk.Label(
            header,
            text="Connecting…",
            bg="#14283f",
            fg="#cbd5e1",
        )
        self.connection.pack(side="right", padx=24)

        nav = ttk.Frame(self.root, padding=(18, 10))
        nav.pack(fill="x")

        self.nav_buttons = {}

        for name in ("Dashboard", "Fleet management", "Reports"):
            button = ttk.Button(
                nav,
                text=name,
                command=lambda value=name: self.show_page(value),
            )
            button.pack(side="left", padx=(0, 8))
            self.nav_buttons[name] = button

        self.body = ttk.Frame(
            self.root,
            padding=(20, 8, 20, 18),
        )
        self.body.pack(fill="both", expand=True)

        self.page_title = ttk.Label(
            self.body,
            style="Title.TLabel",
        )
        self.page_title.pack(anchor="w", pady=(0, 12))

        self.content = ttk.Frame(self.body)
        self.content.pack(fill="both", expand=True)

    def show_page(self, name):
        self.page = name
        self.page_title.configure(text=name)

        for label, button in self.nav_buttons.items():
            button.configure(
                state="disabled" if label == name else "normal"
            )

        for child in self.content.winfo_children():
            child.destroy()

        self.tables.clear()

        with self.selection_lock:
            if name != "Dashboard":
                self.monitor_id = None
                self.latest_preview = None

            if name != "Reports":
                self.log_query = ""

        if name == "Dashboard":
            self.build_dashboard()
        elif name == "Fleet management":
            self.build_fleet()
        else:
            self.build_reports()

        self.render_data()

    # ---------------------------------------------------------
    # Dashboard
    # ---------------------------------------------------------

    def build_dashboard(self):
        self.metrics = ttk.Label(
            self.content,
            style="Metric.TLabel",
        )
        self.metrics.pack(anchor="w", pady=(0, 12))

        split = ttk.Panedwindow(
            self.content,
            orient="horizontal",
        )
        split.pack(fill="both", expand=True)

        left = ttk.Frame(split, padding=(0, 0, 10, 0))
        right = ttk.Frame(split, padding=(10, 0, 0, 0))
        split.add(left, weight=3)
        split.add(right, weight=2)

        ttk.Label(
            left,
            text="Vehicles",
            style="Metric.TLabel",
        ).pack(anchor="w")

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
            "<<TreeviewSelect>>",
            self.dashboard_vehicle_selected,
        )

        self.monitor_heading = ttk.Label(
            right,
            text="Live vehicle view",
            style="Metric.TLabel",
        )
        self.monitor_heading.pack(anchor="w")

        self.monitor_details = ttk.Label(
            right,
            text="Choose a vehicle from the list.",
            justify="left",
            wraplength=430,
        )
        self.monitor_details.pack(anchor="w", pady=(6, 10))

        video_area = tk.Frame(
            right,
            bg="#14283f",
            height=270,
        )
        video_area.pack(fill="both", expand=True)

        self.video = tk.Label(
            video_area,
            text="Waiting for camera…",
            bg="#14283f",
            fg="#dbeafe",
            font=("Segoe UI", 12),
            wraplength=420,
        )
        self.video.place(
            relx=0,
            rely=0,
            relwidth=1,
            relheight=1,
        )

        ttk.Label(
            self.content,
            text="Recent risk alerts",
            style="Metric.TLabel",
        ).pack(anchor="w", pady=(12, 4))

        self.tables["dashboard_logs"] = make_table(
            self.content,
            ("time", "vehicle", "driver", "risk", "reason"),
            [145, 110, 130, 85, 420],
            height=4,
        )

    def dashboard_vehicle_selected(self, _event=None):
        selected = self.tables["dashboard_vehicles"].selection()

        if not selected:
            return

        with self.selection_lock:
            self.monitor_id = int(selected[0])
            self.latest_preview = None

        self.video.configure(
            image="",
            text="Waiting for selected vehicle camera…",
        )
        self.video.image = None
        self.render_monitor()

    def render_monitor(self):
        if self.page != "Dashboard":
            return

        vehicle = next(
            (
                item for item in self.data["vehicles"]
                if item["id"] == self.monitor_id
            ),
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
        readings = sample.get("readings", {})

        state = (
            vehicle_status(vehicle)
            if self.online else "OFFLINE"
        )

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
            self.video.configure(
                image="",
                text="Device or server offline.",
            )
            self.video.image = None

    def render_frame(self, vehicle_id, frame):
        if (
            self.page != "Dashboard"
            or self.monitor_id != vehicle_id
        ):
            return

        try:
            from PIL import Image, ImageTk

            picture = Image.open(BytesIO(frame))
            picture.thumbnail((
                max(1, self.video.winfo_width() - 8),
                max(1, self.video.winfo_height() - 8),
            ))

            photo = ImageTk.PhotoImage(picture)
            self.video.configure(image=photo, text="")
            self.video.image = photo

        except ImportError:
            self.video.configure(
                image="",
                text="Install Pillow to display camera frames.",
            )
            self.video.image = None

        except (OSError, ValueError):
            self.video.configure(
                image="",
                text="Could not decode camera frame.",
            )
            self.video.image = None

    # ---------------------------------------------------------
    # Fleet management
    # ---------------------------------------------------------

    def build_fleet(self):
        notebook = ttk.Notebook(self.content)
        notebook.pack(fill="both", expand=True)
        self.fleet_notebook = notebook

        tabs = (
            ("vehicles", "Vehicles",
             ("id", "registration", "model", "driver", "route", "status")),
            ("drivers", "Drivers",
             ("id", "name", "license", "phone", "vehicle", "status")),
            ("routes", "Routes",
             ("id", "name", "origin", "destination")),
            ("trips", "Assignments",
             ("id", "vehicle", "driver", "route", "started", "ended")),
        )

        for kind, title, columns in tabs:
            frame = ttk.Frame(notebook, padding=10)
            notebook.add(frame, text=title)

            toolbar = ttk.Frame(frame)
            toolbar.pack(fill="x", pady=(0, 8))

            if kind in ENTITY_FIELDS:
                for label, action in (
                    ("Add", lambda k=kind: self.entity_dialog(k)),
                    ("Edit", lambda k=kind: self.edit_selected(k)),
                    ("Delete", lambda k=kind: self.delete_selected(k)),
                ):
                    ttk.Button(
                        toolbar,
                        text=label,
                        command=action,
                    ).pack(side="left", padx=(0, 6))
            else:
                ttk.Button(
                    toolbar,
                    text="Assign / change trip",
                    command=self.assignment_dialog,
                ).pack(side="left")

                ttk.Button(
                    toolbar,
                    text="End selected trip",
                    command=self.end_selected_trip,
                ).pack(side="left", padx=8)

            self.tables[kind] = make_table(
                frame,
                columns,
                height=16,
            )

            if kind in ("vehicles", "drivers"):
                self.tables[kind].bind(
                    "<Double-1>",
                    lambda event, k=kind: self.open_live_from_fleet(k),
                )

            if kind == "trips":
                ttk.Label(
                    frame,
                    text=(
                        "Changing an assignment ends the previous trip "
                        "and keeps its history."
                    ),
                    style="Subtitle.TLabel",
                ).pack(anchor="w", pady=(6, 0))

        notebook.bind(
            "<<NotebookTabChanged>>",
            self.fleet_tab_changed,
        )

    def fleet_tab_changed(self, _event=None):
        index = self.fleet_notebook.index(
            self.fleet_notebook.select()
        )
        self.fleet_tab = (
            "vehicles", "drivers", "routes", "trips"
        )[index]

    def selected_id(self, kind):
        table = self.tables.get(kind)
        selected = table.selection() if table else ()

        if not selected:
            messagebox.showinfo(
                "Select a record",
                "Select a row first.",
                parent=self.root,
            )
            return None

        return int(selected[0])

    def edit_selected(self, kind):
        record_id = self.selected_id(kind)

        if record_id is None:
            return

        record = next(
            (
                item for item in self.data[kind]
                if item["id"] == record_id
            ),
            None,
        )

        if record:
            self.entity_dialog(kind, record)

    def delete_selected(self, kind):
        record_id = self.selected_id(kind)

        if record_id is None:
            return

        if not messagebox.askyesno(
            "Confirm deletion",
            f"Delete this {ENTITY_NAMES[kind]}?",
            parent=self.root,
        ):
            return

        self.submit(
            "/delete-entity",
            {"kind": kind, "id": record_id},
            lambda _result: self.refresh_after_change(),
        )

    def entity_dialog(self, kind, record=None):
        fields = ENTITY_FIELDS[kind]

        dialog = tk.Toplevel(self.root)
        dialog.title(
            ("Edit " if record else "Add ")
            + ENTITY_NAMES[kind]
        )
        dialog.transient(self.root)
        dialog.grab_set()

        frame = ttk.Frame(dialog, padding=22)
        frame.pack(fill="both", expand=True)

        entries = {}

        for index, field in enumerate(fields):
            ttk.Label(
                frame,
                text=field.replace("_", " ").title(),
            ).grid(
                row=index,
                column=0,
                sticky="w",
                padx=(0, 18),
                pady=8,
            )

            variable = tk.StringVar(
                value=record.get(field, "") if record else ""
            )

            ttk.Entry(
                frame,
                textvariable=variable,
                width=36,
            ).grid(row=index, column=1, pady=8)

            entries[field] = variable

        def save():
            values = {
                key: value.get().strip()
                for key, value in entries.items()
            }

            if record:
                values["id"] = record["id"]

            def finished(_result):
                if dialog.winfo_exists():
                    dialog.destroy()
                self.refresh_after_change()

            self.submit(
                "/entity",
                {"kind": kind, "values": values},
                finished,
            )

        ttk.Button(
            frame,
            text="Save",
            command=save,
        ).grid(
            row=len(fields),
            column=1,
            sticky="e",
            pady=(12, 0),
        )

        dialog.bind("<Return>", lambda _event: save())

    def refresh_after_change(self):
        self.submit(
            "/snapshot",
            None,
            self.update_snapshot,
        )

    def update_snapshot(self, result):
        self.data = result
        self.render_data()

    def assignment_dialog(self):
        if any(
            not self.data[key]
            for key in ("vehicles", "drivers", "routes")
        ):
            messagebox.showinfo(
                "Missing records",
                "Add a vehicle, driver, and route first.",
                parent=self.root,
            )
            return

        dialog = tk.Toplevel(self.root)
        dialog.title("Assign driver and route")
        dialog.transient(self.root)
        dialog.grab_set()

        frame = ttk.Frame(dialog, padding=22)
        frame.pack()

        choices = {}

        for index, (kind, field) in enumerate((
            ("vehicles", "registration"),
            ("drivers", "name"),
            ("routes", "name"),
        )):
            ttk.Label(
                frame,
                text=ENTITY_NAMES[kind].title(),
            ).grid(
                row=index,
                column=0,
                sticky="w",
                padx=(0, 14),
                pady=9,
            )

            combo = ttk.Combobox(
                frame,
                state="readonly",
                values=[
                    f'{item["id"]} — {item[field]}'
                    for item in self.data[kind]
                ],
                width=38,
            )
            combo.grid(row=index, column=1, pady=9)
            combo.current(0)

            choices[f"{ENTITY_NAMES[kind]}_id"] = combo

        def save():
            try:
                payload = {
                    key: int(combo.get().split(" — ", 1)[0])
                    for key, combo in choices.items()
                }
            except (ValueError, IndexError):
                messagebox.showerror(
                    "Invalid selection",
                    "Choose a vehicle, driver, and route.",
                    parent=dialog,
                )
                return

            def finished(_result):
                if dialog.winfo_exists():
                    dialog.destroy()
                self.refresh_after_change()

            self.submit("/assign", payload, finished)

        ttk.Button(
            frame,
            text="Start trip",
            command=save,
        ).grid(row=3, column=1, sticky="e", pady=(12, 0))

    def end_selected_trip(self):
        trip_id = self.selected_id("trips")

        if trip_id is None:
            return

        if messagebox.askyesno(
            "End trip",
            "End the selected active trip?",
            parent=self.root,
        ):
            self.submit(
                "/end-trip",
                {"trip_id": trip_id},
                lambda _result: self.refresh_after_change(),
            )

    def open_live_from_fleet(self, kind):
        record_id = self.selected_id(kind)

        if record_id is None:
            return

        if kind == "drivers":
            vehicle = next(
                (
                    item for item in self.data["vehicles"]
                    if item.get("trip")
                    and item["trip"]["driver_id"] == record_id
                ),
                None,
            )

            if not vehicle:
                messagebox.showinfo(
                    "No active trip",
                    "This driver has no active vehicle.",
                    parent=self.root,
                )
                return

            record_id = vehicle["id"]

        self.show_page("Dashboard")

        with self.selection_lock:
            self.monitor_id = record_id

        self.render_data()

    # ---------------------------------------------------------
    # Reports
    # ---------------------------------------------------------

    def build_reports(self):
        controls = ttk.Frame(self.content)
        controls.pack(fill="x")
        self.filters = {}

        options = (
            (
                "Vehicle", "vehicle_id",
                ["ALL"] + [
                    f'{v["id"]} — {v["registration"]}'
                    for v in self.data["vehicles"]
                ],
            ),
            (
                "Driver", "driver_id",
                ["ALL"] + [
                    f'{d["id"]} — {d["name"]}'
                    for d in self.data["drivers"]
                ],
            ),
            (
                "Risk", "level",
                ["ALL", "LOW", "CAUTION", "HIGH", "UNKNOWN"],
            ),
        )

        for column, (label, key, values) in enumerate(options):
            ttk.Label(
                controls,
                text=label,
            ).grid(row=0, column=column, sticky="w")

            combo = ttk.Combobox(
                controls,
                state="readonly",
                values=values,
                width=23,
            )
            combo.grid(
                row=1,
                column=column,
                sticky="w",
                padx=(0, 10),
                pady=5,
            )
            combo.current(0)
            self.filters[key] = combo

        for column, key, label in (
            (0, "since", "From date (YYYY-MM-DD)"),
            (1, "until", "To date (YYYY-MM-DD)"),
        ):
            ttk.Label(
                controls,
                text=label,
            ).grid(row=2, column=column, sticky="w")

            entry = ttk.Entry(controls, width=25)
            entry.grid(
                row=3,
                column=column,
                sticky="w",
                padx=(0, 10),
                pady=5,
            )
            self.filters[key] = entry

        ttk.Button(
            controls,
            text="Apply filters",
            command=self.apply_filters,
        ).grid(row=3, column=2, sticky="w", padx=6)

        ttk.Button(
            controls,
            text="Export CSV",
            command=self.export_logs,
        ).grid(row=3, column=3, sticky="w", padx=6)

        self.report_summary = ttk.Label(
            self.content,
            text="Showing up to 1,000 risk-level changes.",
            style="Subtitle.TLabel",
        )
        self.report_summary.pack(anchor="w", pady=8)

        self.tables["reports"] = make_table(
            self.content,
            (
                "time", "vehicle", "driver", "route",
                "risk", "score", "reason",
            ),
            [145, 110, 130, 110, 85, 65, 350],
            height=15,
        )

    def apply_filters(self):
        filters = {}

        try:
            for key, widget in self.filters.items():
                value = widget.get().strip()

                if value in ("", "ALL"):
                    continue

                if key in ("since", "until"):
                    date = datetime.strptime(
                        value,
                        "%Y-%m-%d",
                    ).date()

                    bound = (
                        time.min if key == "since" else time.max
                    )

                    local_bound = datetime.combine(
                        date,
                        bound,
                    ).astimezone()

                    value = local_bound.astimezone(
                        timezone.utc
                    ).isoformat(timespec="milliseconds")

                elif key in ("vehicle_id", "driver_id"):
                    value = value.split(" — ", 1)[0]

                filters[key] = value

            if (
                filters.get("since", "")
                > filters.get("until", "9999")
            ):
                raise ValueError(
                    "Start date must not be after end date."
                )

        except ValueError as error:
            messagebox.showerror(
                "Invalid filter",
                str(error),
                parent=self.root,
            )
            return

        with self.selection_lock:
            self.log_query = "?" + urlencode(filters)

        self.submit_refresh_logs()

    def submit_refresh_logs(self):
        with self.selection_lock:
            query = self.log_query

        self.submit("/logs" + query, None, self.set_logs)

    def set_logs(self, result):
        self.logs = result

        if self.page == "Reports":
            self.render_reports()

    def export_logs(self):
        path = filedialog.asksaveasfilename(
            parent=self.root,
            defaultextension=".csv",
            filetypes=[("CSV file", "*.csv")],
            initialfile="fleet-risk-events.csv",
        )

        if not path:
            return

        fields = (
            "captured_at", "vehicle_name", "driver_name",
            "route_name", "level", "score", "reason", "trip_id",
        )

        try:
            with open(
                path,
                "w",
                newline="",
                encoding="utf-8-sig",
            ) as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=fields,
                    extrasaction="ignore",
                )
                writer.writeheader()

                for record in self.logs:
                    safe = {
                        key: (
                            "'" + value
                            if isinstance(value, str)
                            and value.startswith(("=", "+", "-", "@"))
                            else value
                        )
                        for key, value in record.items()
                    }
                    writer.writerow(safe)

        except OSError as error:
            messagebox.showerror(
                "Export failed",
                str(error),
                parent=self.root,
            )
            return

        messagebox.showinfo(
            "Export complete",
            f"Saved {len(self.logs)} events.",
            parent=self.root,
        )

    # ---------------------------------------------------------
    # Background workers and preview selection
    # ---------------------------------------------------------

    def worker(self):
        """Process API commands, refresh dashboard and renew preview lease."""
        while not self.stop.is_set():
            try:
                while True:
                    path, payload, callback = (
                        self.commands.get_nowait()
                    )

                    try:
                        result = self.api.request(path, payload)
                        self.events.put(("done", (callback, result)))
                    except ApiError as error:
                        self.events.put(("error", str(error)))

            except queue.Empty:
                pass

            try:
                self.events.put((
                    "snapshot",
                    self.api.request("/snapshot"),
                ))

                with self.selection_lock:
                    query = self.log_query
                    selected = (
                        self.monitor_id
                        if self.page == "Dashboard"
                        else None
                    )

                self.events.put((
                    "logs",
                    self.api.request("/logs" + query),
                ))

                # Refresh the selection lease every second.
                self.api.request(
                    "/preview-selection",
                    {"vehicle_id": selected},
                )

            except ApiError as error:
                self.events.put(("offline", str(error)))

            self.stop.wait(1)

    def preview_worker(self):
        """Fetch only the currently selected vehicle's camera frame."""
        while not self.stop.is_set():
            with self.selection_lock:
                vehicle = (
                    self.monitor_id
                    if self.page == "Dashboard"
                    else None
                )

            if vehicle is not None:
                try:
                    frame = self.api.request(
                        f"/frame/{vehicle}",
                        raw=True,
                    )
                    result = (vehicle, frame, "")
                except ApiError as error:
                    result = (vehicle, None, str(error))

                with self.selection_lock:
                    self.latest_preview = result

            self.stop.wait(0.15)

    # ---------------------------------------------------------
    # Event processing
    # ---------------------------------------------------------

    def drain_events(self):
        if self.stop.is_set():
            return

        while True:
            try:
                kind, value = self.events.get_nowait()
            except queue.Empty:
                break

            if kind == "snapshot":
                self.data = value
                self.online = True
                self.connection.configure(
                    text="Connected • Live updates",
                    fg="#86efac",
                )
                self.render_data()

            elif kind == "logs":
                self.logs = value

                if self.page == "Dashboard":
                    self.render_dashboard_logs()
                elif self.page == "Reports":
                    self.render_reports()

            elif kind == "offline":
                self.online = False
                self.connection.configure(
                    text="Server offline • Showing last data",
                    fg="#fca5a5",
                )
                self.render_data()

            elif kind == "error":
                messagebox.showerror(
                    "Could not complete action",
                    value,
                    parent=self.root,
                )

            elif kind == "done":
                callback, result = value
                if callback:
                    callback(result)

        with self.selection_lock:
            preview = self.latest_preview
            self.latest_preview = None
            selected = self.monitor_id

        if (
            preview
            and self.page == "Dashboard"
            and preview[0] == selected
        ):
            if preview[1]:
                self.render_frame(preview[0], preview[1])
            elif hasattr(self, "video"):
                self.video.configure(
                    image="",
                    text="Camera frame not currently available.",
                )
                self.video.image = None

        self.root.after(100, self.drain_events)

    def submit(self, path, payload=None, callback=None):
        self.commands.put((path, payload, callback))

    # ---------------------------------------------------------
    # Rendering
    # ---------------------------------------------------------

    def render_data(self):
        if not self.online and not any(self.data.values()):
            return

        if self.page == "Dashboard":
            self.render_dashboard()
        elif self.page == "Fleet management":
            self.render_fleet()
        elif self.page == "Reports":
            self.render_reports()

    def render_dashboard(self):
        vehicles = self.data["vehicles"]

        statuses = [
            vehicle_status(v) if self.online else "OFFLINE"
            for v in vehicles
        ]

        active = sum(bool(v.get("trip")) for v in vehicles)

        online_count = sum(
            status in ("LOW", "CAUTION", "HIGH", "UNKNOWN")
            for status in statuses
        )

        self.metrics.configure(
            text=(
                f'{len(vehicles)} vehicles     '
                f'{active} active trips     '
                f'{online_count} online     '
                f'{statuses.count("HIGH")} high risk     '
                f'{statuses.count("CAUTION")} caution'
            )
        )

        rows = []

        for vehicle, status in zip(vehicles, statuses):
            trip = vehicle.get("trip") or {}
            sample = vehicle.get("sample") or {}

            rows.append((
                vehicle["id"],
                (
                    vehicle["registration"],
                    trip.get("driver_name", "—"),
                    trip.get("route_name", "—"),
                    status,
                    sample.get("score", "—")
                    if status != "OFFLINE" else "—",
                ),
                (status,),
            ))

        fill_table(self.tables["dashboard_vehicles"], rows)

        if self.monitor_id is None and vehicles:
            first = vehicles[0]
            self.monitor_id = first["id"]
            self.tables["dashboard_vehicles"].selection_set(
                str(first["id"])
            )

        self.render_monitor()
        self.render_dashboard_logs()

    def render_dashboard_logs(self):
        if "dashboard_logs" not in self.tables:
            return

        rows = [
            (
                entry["id"],
                (
                    local_time(entry["captured_at"]),
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

    def render_fleet(self):
        vehicles = self.data["vehicles"]
        drivers = self.data["drivers"]

        active_drivers = {
            v["trip"]["driver_id"]: v
            for v in vehicles if v.get("trip")
        }

        rows_by_kind = {
            "vehicles": [
                (
                    v["id"],
                    (
                        v["id"],
                        v["registration"],
                        v["model"],
                        (v.get("trip") or {}).get("driver_name", "—"),
                        (v.get("trip") or {}).get("route_name", "—"),
                        (
                            live_status(
                                vehicle_status(v),
                                (v.get("sample") or {}).get("readings", {}),
                            )
                            if self.online else "OFFLINE"
                        ),
                    ),
                    (vehicle_status(v) if self.online else "OFFLINE",),
                )
                for v in vehicles
            ],
            "drivers": [
                (
                    d["id"],
                    (
                        d["id"],
                        d["name"],
                        d["license"],
                        d["phone"],
                        active_drivers[d["id"]]["registration"]
                        if d["id"] in active_drivers else "—",
                        (
                            vehicle_status(active_drivers[d["id"]])
                            if self.online else "OFFLINE"
                        )
                        if d["id"] in active_drivers else "NO TRIP",
                    ),
                    (),
                )
                for d in drivers
            ],
            "routes": [
                (
                    r["id"],
                    (r["id"], r["name"], r["origin"], r["destination"]),
                    (),
                )
                for r in self.data["routes"]
            ],
            "trips": [
                (
                    t["id"],
                    (
                        t["id"],
                        t["vehicle_name"],
                        t["driver_name"],
                        t["route_name"],
                        local_time(t["started_at"]),
                        local_time(t["ended_at"])
                        if t["ended_at"] else "ACTIVE",
                    ),
                    (),
                )
                for t in self.data["trips"]
            ],
        }

        for kind, rows in rows_by_kind.items():
            if kind in self.tables:
                fill_table(self.tables[kind], rows)

    def render_reports(self):
        if "reports" not in self.tables:
            return

        rows = [
            (
                entry["id"],
                (
                    local_time(entry["captured_at"]),
                    entry["vehicle_name"],
                    entry["driver_name"],
                    entry["route_name"],
                    entry["level"],
                    entry["score"],
                    entry["reason"],
                ),
                (entry["level"],),
            )
            for entry in self.logs
        ]

        fill_table(self.tables["reports"], rows)

        self.report_summary.configure(
            text=(
                f"Showing {len(self.logs)} matching risk transitions "
                "(maximum 1,000)."
            )
        )

    # ---------------------------------------------------------
    # Shutdown
    # ---------------------------------------------------------

    def close(self):
        self.stop.set()

        # The selection lease will also expire automatically if the
        # manager exits before this request reaches the server.
        try:
            self.api.request(
                "/preview-selection",
                {"vehicle_id": None},
            )
        except ApiError:
            pass

        try:
            self.root.destroy()
        except tk.TclError:
            pass
