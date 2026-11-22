"""Owner dashboard. Worker thread handles HTTP; Tkinter stays on the main thread."""
import csv
from datetime import datetime, time, timezone
from io import BytesIO
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from urllib.parse import urlencode

from ..perception.face_preview import behavior_label, classifier_summary
from .network import ApiError
from .ui_common import COLORS, fill_table, local_time, make_table, setup_style, vehicle_status


def live_status(state, readings):
    if state == "UNKNOWN":
        if readings.get("source") == "trained_model" and readings.get("speed_method") == "unavailable":
            return "Camera only"
        return "Awaiting assessment"
    if state == "LOW" and readings.get("speed") == 0:
        return "Stopped"
    return state


class OwnerApp:
    def __init__(self, root, api):
        self.root, self.api = root, api
        self.data = {name: [] for name in ("vehicles", "drivers", "routes", "trips")}
        self.logs = []
        self.events = queue.Queue()
        self.commands = queue.Queue()
        self.stop = threading.Event()
        self.selection_lock = threading.Lock()
        self.monitor_id = None
        self.latest_preview = None
        self.log_query = ""
        self.page = ""
        self.table = None
        self.online = False
        root.title("Fleet Guardian • Owner console")
        root.geometry("1280x800")
        root.minsize(1000, 650)
        setup_style(root)
        self.build_shell()
        self.show_page("Overview")
        root.protocol("WM_DELETE_WINDOW", self.close)
        threading.Thread(target=self.worker, daemon=True).start()
        threading.Thread(target=self.preview_worker, daemon=True).start()
        root.after(100, self.drain_events)

    def build_shell(self):
        sidebar = tk.Frame(self.root, bg="#14283f", width=205)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)
        tk.Label(sidebar, text="FLEET\nGUARDIAN", bg="#14283f", fg="white", font=("Segoe UI", 17, "bold"), justify="left", anchor="w").pack(anchor="w", padx=20, pady=(30, 8))
        tk.Label(sidebar, text="Owner console", bg="#14283f", fg="#a5bed9", font=("Segoe UI", 11)).pack(anchor="w", padx=22, pady=(0, 28))
        self.nav_buttons = {}
        for name in ("Overview", "Vehicles", "Drivers", "Routes", "Assignments", "Live monitoring", "Logs & reports"):
            button = tk.Button(sidebar, text=name, anchor="w", relief="flat", bd=0,
                               bg="#14283f", fg="white", activebackground="#284662", activeforeground="white",
                               font=("Segoe UI", 11), padx=20, pady=12,
                               command=lambda page=name: self.show_page(page))
            button.pack(fill="x", padx=8, pady=2)
            self.nav_buttons[name] = button
        tk.Label(sidebar, text="PYTHON LAB PROJECT\nCamera model supported", justify="left",
                 bg="#14283f", fg="#a5bed9", font=("Segoe UI", 8), anchor="w", wraplength=170).pack(side="bottom", padx=16, pady=24)
        main = ttk.Frame(self.root, padding=24)
        main.pack(side="left", fill="both", expand=True)
        self.title = ttk.Label(main, style="Title.TLabel")
        self.title.pack(anchor="w")
        self.connection = ttk.Label(main, text="Connecting to fleet server…", style="Subtitle.TLabel")
        self.connection.pack(anchor="w", pady=(6, 18))
        self.content = ttk.Frame(main)
        self.content.pack(fill="both", expand=True)

    def worker(self):
        while not self.stop.is_set():
            try:
                while not self.commands.empty():
                    path, payload, callback = self.commands.get_nowait()
                    try:
                        result = self.api.request(path, payload)
                        self.events.put(("done", (callback, result)))
                    except ApiError as error:
                        self.events.put(("error", str(error)))
                snapshot = self.api.request("/snapshot")
                self.events.put(("snapshot", snapshot))
                with self.selection_lock:
                    query = self.log_query
                self.events.put(("logs", self.api.request("/logs" + query)))
            except ApiError as error:
                self.events.put(("offline", str(error)))
            self.stop.wait(1)

    def preview_worker(self):
        while not self.stop.is_set():
            with self.selection_lock:
                vehicle = self.monitor_id
            if vehicle:
                try:
                    frame = self.api.request(f"/frame/{vehicle}", raw=True)
                    preview = (vehicle, frame, "")
                except ApiError as error:
                    preview = (vehicle, None, str(error))
                with self.selection_lock:
                    self.latest_preview = preview
            self.stop.wait(.12)

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
                self.connection.configure(text="Connected  •  Updates every second  •  Sensor source shown for each vehicle", foreground="#16734b")
                self.render_data()
            elif kind == "logs":
                self.logs = value
                if self.page in ("Overview", "Logs & reports"):
                    self.render_logs()
            elif kind == "offline":
                self.online = False
                self.connection.configure(text=value + "  •  Displaying last received data", foreground="#bf293b")
                self.render_data()
            elif kind == "error":
                messagebox.showerror("Could not save", value, parent=self.root)
            elif kind == "done":
                callback, result = value
                if callback:
                    callback(result)
            elif kind == "frame":
                self.render_frame(*value)
            elif kind == "frame_missing" and self.page == "Live monitoring" and value[0] == self.monitor_id:
                self.video.configure(image="", text=value[1])
                self.video.image = None
        with self.selection_lock:
            preview, self.latest_preview = self.latest_preview, None
        if preview and self.page == "Live monitoring" and preview[0] == self.monitor_id:
            if preview[1]:
                self.render_frame(preview[0], preview[1])
            else:
                self.video.configure(image="", text=preview[2])
                self.video.image = None
        self.root.after(80, self.drain_events)

    def submit(self, path, payload, callback=None):
        self.commands.put((path, payload, callback))

    def show_page(self, name):
        self.page = name
        self.title.configure(text=name)
        for label, button in self.nav_buttons.items():
            button.configure(bg="#284662" if label == name else "#14283f")
        for widget in self.content.winfo_children():
            widget.destroy()
        self.table = None
        with self.selection_lock:
            if name != "Live monitoring":
                self.monitor_id = None
            self.log_query = ""
        if name == "Overview":
            self.build_overview()
        elif name in ("Vehicles", "Drivers", "Routes"):
            self.build_entities(name.lower())
        elif name == "Assignments":
            self.build_assignments()
        elif name == "Live monitoring":
            self.build_monitor()
        else:
            self.build_logs()
        self.render_data()

    def build_overview(self):
        ttk.Label(self.content, text="Fleet status", style="Metric.TLabel").pack(anchor="w")
        self.metrics = ttk.Label(self.content, style="Metric.TLabel", wraplength=950)
        self.metrics.pack(anchor="w", pady=15)
        ttk.Label(self.content, text="Double-click a vehicle to open its live measurements and camera.", style="Subtitle.TLabel").pack(anchor="w")
        self.table = make_table(self.content, ("vehicle", "driver", "route", "state", "risk", "source"), height=4)
        self.table.bind("<Double-1>", lambda event: self.open_selected_vehicle())
        ttk.Label(self.content, text="Recent risk transitions", style="Metric.TLabel").pack(anchor="w", pady=(12, 0))
        self.log_table = make_table(self.content, ("time", "vehicle", "driver", "level", "reason"), [145, 110, 140, 85, 380], height=4)

    def build_entities(self, kind):
        toolbar = ttk.Frame(self.content)
        toolbar.pack(fill="x")
        ttk.Button(toolbar, text="Add " + kind[:-1], command=lambda: self.entity_dialog(kind)).pack(side="left")
        ttk.Button(toolbar, text="Edit selected", command=lambda: self.edit_selected(kind)).pack(side="left", padx=8)
        if kind in ("vehicles", "drivers"):
            ttk.Button(toolbar, text="Open live monitoring", command=lambda: self.open_selected_vehicle(kind)).pack(side="left")
        columns = {"vehicles": ("id", "registration", "model", "driver", "route", "state"),
                   "drivers": ("id", "name", "license", "phone", "vehicle", "risk"),
                   "routes": ("id", "name", "origin", "destination")}[kind]
        self.table = make_table(self.content, columns)
        if kind != "routes":
            self.table.bind("<Double-1>", lambda event: self.open_selected_vehicle(kind))
        ttk.Label(self.content, text="Records stay available for historical reports. Use Assignments to change active trips.", style="Subtitle.TLabel").pack(anchor="w")

    def selected_id(self):
        selected = self.table.selection() if self.table else ()
        if not selected:
            messagebox.showinfo("Select a record", "Select a row first.", parent=self.root)
            return None
        return int(selected[0])

    def edit_selected(self, kind):
        record_id = self.selected_id()
        if record_id:
            record = next(item for item in self.data[kind] if item["id"] == record_id)
            self.entity_dialog(kind, record)

    def entity_dialog(self, kind, record=None):
        fields = {"vehicles": ("registration", "model"), "drivers": ("name", "license", "phone"), "routes": ("name", "origin", "destination")}[kind]
        dialog = tk.Toplevel(self.root)
        dialog.title(("Edit " if record else "Add ") + kind[:-1])
        dialog.transient(self.root)
        dialog.grab_set()
        frame = ttk.Frame(dialog, padding=24)
        frame.pack(fill="both", expand=True)
        entries = {}
        for index, field in enumerate(fields):
            ttk.Label(frame, text=field.title()).grid(row=index, column=0, sticky="w", padx=(0, 20), pady=10)
            variable = tk.StringVar(value=record.get(field, "") if record else "")
            ttk.Entry(frame, textvariable=variable, width=38).grid(row=index, column=1, pady=10)
            entries[field] = variable
        def save():
            values = {key: value.get() for key, value in entries.items()}
            if record:
                values["id"] = record["id"]
            self.submit("/entity", {"kind": kind, "values": values}, lambda result: dialog.destroy() if dialog.winfo_exists() else None)
        ttk.Button(frame, text="Save", command=save).grid(row=len(fields), column=1, sticky="e", pady=14)

    def build_assignments(self):
        toolbar = ttk.Frame(self.content)
        toolbar.pack(fill="x")
        ttk.Button(toolbar, text="Assign / change trip", command=self.assignment_dialog).pack(side="left")
        ttk.Button(toolbar, text="End selected trip", command=self.end_selected_trip).pack(side="left", padx=10)
        ttk.Label(self.content, text="Changing an assignment closes the previous trip and preserves its logs.", style="Subtitle.TLabel").pack(anchor="w", pady=10)
        self.table = make_table(self.content, ("trip", "vehicle", "driver", "route", "started", "ended"))

    def assignment_dialog(self):
        if any(not self.data[key] for key in ("vehicles", "drivers", "routes")):
            messagebox.showinfo("Missing records", "Add at least one vehicle, driver, and route first.")
            return
        dialog = tk.Toplevel(self.root)
        dialog.title("Assign driver and route")
        dialog.transient(self.root)
        dialog.grab_set()
        frame = ttk.Frame(dialog, padding=24)
        frame.pack()
        choices = {}
        for index, (kind, field) in enumerate((("vehicles", "registration"), ("drivers", "name"), ("routes", "name"))):
            ttk.Label(frame, text=kind[:-1].title()).grid(row=index, column=0, padx=10, pady=12)
            values = [f"{item['id']} — {item[field]}" for item in self.data[kind]]
            combo = ttk.Combobox(frame, state="readonly", values=values, width=40)
            combo.grid(row=index, column=1)
            combo.current(0)
            choices[kind[:-1] + "_id"] = combo
        def save():
            payload = {key: int(combo.get().split(" — ")[0]) for key, combo in choices.items()}
            self.submit("/assign", payload, lambda result: dialog.destroy() if dialog.winfo_exists() else None)
        ttk.Button(frame, text="Start replacement trip", command=save).grid(row=3, column=1, sticky="e", pady=18)

    def end_selected_trip(self):
        trip_id = self.selected_id()
        if trip_id:
            self.submit("/end-trip", {"trip_id": trip_id})

    def open_selected_vehicle(self, kind="vehicles"):
        record_id = self.selected_id()
        if not record_id:
            return
        if kind == "drivers":
            vehicle = next((vehicle for vehicle in self.data["vehicles"] if vehicle["trip"] and vehicle["trip"]["driver_id"] == record_id), None)
            if not vehicle:
                messagebox.showinfo("No active trip", "This driver has no active vehicle. Their history is available under Logs & reports.")
                return
            record_id = vehicle["id"]
        self.show_page("Live monitoring")
        self.choose_vehicle(record_id)

    def build_monitor(self):
        toolbar = ttk.Frame(self.content)
        toolbar.pack(fill="x")
        ttk.Label(toolbar, text="Vehicle").pack(side="left", padx=(0, 10))
        self.vehicle_combo = ttk.Combobox(toolbar, state="readonly", width=45)
        self.vehicle_combo.pack(side="left")
        self.vehicle_combo.bind("<<ComboboxSelected>>", lambda event: self.choose_vehicle(int(self.vehicle_combo.get().split(" — ")[0])))
        self.monitor_heading = ttk.Label(self.content, text="Select a vehicle", style="Metric.TLabel")
        self.monitor_heading.pack(anchor="w", pady=(20, 8))
        self.monitor_details = ttk.Label(self.content, wraplength=900, justify="left")
        self.monitor_details.pack(anchor="w", pady=(0, 14))
        video_area = tk.Frame(self.content, bg="#14283f", height=80)
        video_area.pack(fill="both", expand=True)
        self.video = tk.Label(video_area, text="Camera sharing is off.\nEnable it in the vehicle's driver window.", bg="#14283f", fg="#dbeafe", font=("Segoe UI", 13), wraplength=850)
        self.video.place(relx=0, rely=0, relwidth=1, relheight=1)

    def choose_vehicle(self, vehicle_id):
        with self.selection_lock:
            self.monitor_id = vehicle_id
        vehicle = next((v for v in self.data["vehicles"] if v["id"] == vehicle_id), None)
        if vehicle:
            self.vehicle_combo.set(f"{vehicle_id} — {vehicle['registration']}")
        self.video.configure(image="", text="Waiting for this vehicle's camera…")
        self.video.image = None
        self.render_monitor()

    def render_frame(self, vehicle_id, frame):
        if self.page != "Live monitoring" or self.monitor_id != vehicle_id:
            return
        try:
            from PIL import Image, ImageTk
            picture = Image.open(BytesIO(frame))
            picture.thumbnail((max(1, self.video.winfo_width() - 8),
                               max(1, self.video.winfo_height() - 8)))
            photo = ImageTk.PhotoImage(picture)
            self.video.configure(image=photo, text="", width=0, height=0)
            self.video.image = photo
        except ImportError:
            self.video.configure(text="Install Pillow to display camera frames.", image="")
        except (OSError, ValueError):
            self.video.configure(text="Could not decode camera frame.", image="")

    def build_logs(self):
        controls = ttk.Frame(self.content)
        controls.pack(fill="x")
        self.filters = {}
        for index, (label, key, values) in enumerate((
            ("Vehicle", "vehicle_id", ["ALL"] + [f"{v['id']} — {v['registration']}" for v in self.data["vehicles"]]),
            ("Driver", "driver_id", ["ALL"] + [f"{d['id']} — {d['name']}" for d in self.data["drivers"]]),
            ("Level", "level", ["ALL", "LOW", "CAUTION", "HIGH", "UNKNOWN"]))):
            ttk.Label(controls, text=label).grid(row=0, column=index, sticky="w")
            combo = ttk.Combobox(controls, state="readonly", values=values, width=23)
            combo.grid(row=1, column=index, padx=(0, 8), pady=6)
            combo.current(0)
            self.filters[key] = combo
        for column, key, label in ((0, "since", "From date (YYYY-MM-DD)"), (1, "until", "To date (YYYY-MM-DD)")):
            ttk.Label(controls, text=label).grid(row=2, column=column, sticky="w")
            entry = ttk.Entry(controls, width=26)
            entry.grid(row=3, column=column, sticky="w", pady=6)
            self.filters[key] = entry
        ttk.Button(controls, text="Apply filters", command=self.apply_filters).grid(row=3, column=2, sticky="w")
        ttk.Button(controls, text="Export shown rows to CSV", command=self.export_logs).grid(row=3, column=3, padx=10)
        self.log_summary = ttk.Label(self.content, text="Latest 1,000 matching risk transitions. Raw telemetry is retained in SQLite.", style="Subtitle.TLabel")
        self.log_summary.pack(anchor="w", pady=8)
        self.log_table = make_table(self.content, ("time", "vehicle", "driver", "route", "level", "score", "reason"), [145, 110, 135, 100, 85, 60, 350])

    def apply_filters(self):
        filters = {}
        try:
            for key, widget in self.filters.items():
                value = widget.get().strip()
                if value in ("", "ALL"):
                    continue
                if key in ("since", "until"):
                    date = datetime.strptime(value, "%Y-%m-%d").date()
                    value = datetime.combine(date, time.min if key == "since" else time.max).astimezone().astimezone(timezone.utc).isoformat(timespec="milliseconds")
                else:
                    value = value.split(" — ")[0]
                filters[key] = value
            if filters.get("since", "") > filters.get("until", "9999"):
                raise ValueError("Start date must not be after end date.")
        except ValueError as error:
            messagebox.showerror("Invalid date", str(error), parent=self.root)
            return
        with self.selection_lock:
            self.log_query = "?" + urlencode(filters)

    def export_logs(self):
        path = filedialog.asksaveasfilename(parent=self.root, defaultextension=".csv", filetypes=[("CSV file", "*.csv")], initialfile="fleet-risk-events.csv")
        if not path:
            return
        fields = ("captured_at", "vehicle_name", "driver_name", "route_name", "level", "score", "reason", "trip_id")
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
                writer.writeheader()
                for record in self.logs:
                    # Prevent spreadsheet formula interpretation of user-entered names.
                    safe = {key: ("'" + value if isinstance(value, str) and value.startswith(("=", "+", "-", "@")) else value) for key, value in record.items()}
                    writer.writerow(safe)
        except OSError as error:
            messagebox.showerror("Export failed", str(error), parent=self.root)
            return
        messagebox.showinfo("Export complete", f"Saved {len(self.logs)} events.", parent=self.root)

    def render_data(self):
        vehicles = self.data["vehicles"]
        if self.page == "Overview":
            statuses = [vehicle_status(v) if self.online else "OFFLINE" for v in vehicles]
            online = sum(status in ("LOW", "CAUTION", "HIGH", "UNKNOWN") for status in statuses)
            active = sum(v["trip"] is not None for v in vehicles)
            self.metrics.configure(text=f"{len(vehicles)} vehicles     {active} active trips     {online} online\n{statuses.count('HIGH')} high risk     {statuses.count('CAUTION')} caution     {statuses.count('UNKNOWN')} unable to assess")
            rows = []
            for vehicle, status in zip(vehicles, statuses):
                trip, sample = vehicle["trip"] or {}, vehicle["sample"] or {}
                rows.append((vehicle["id"], (vehicle["registration"], trip.get("driver_name", "—"), trip.get("route_name", "—"), status, sample.get("score", "—") if status != "OFFLINE" else "—", sample.get("readings", {}).get("source", "—")), (status,)))
            fill_table(self.table, rows)
            self.render_logs()
        elif self.page == "Vehicles":
            fill_table(self.table, [(v["id"], (v["id"], v["registration"], v["model"], (v["trip"] or {}).get("driver_name", "—"), (v["trip"] or {}).get("route_name", "—"), live_status(vehicle_status(v), (v["sample"] or {}).get("readings", {})) if self.online else "OFFLINE"), ()) for v in vehicles])
        elif self.page == "Drivers":
            rows = []
            for driver in self.data["drivers"]:
                vehicle = next((v for v in vehicles if v["trip"] and v["trip"]["driver_id"] == driver["id"]), None)
                state = (vehicle_status(vehicle) if self.online else "OFFLINE") if vehicle else "NO TRIP"
                rows.append((driver["id"], (driver["id"], driver["name"], driver["license"], driver["phone"], vehicle["registration"] if vehicle else "—", state), (state,)))
            fill_table(self.table, rows)
        elif self.page == "Routes":
            fill_table(self.table, [(r["id"], (r["id"], r["name"], r["origin"], r["destination"]), ()) for r in self.data["routes"]])
        elif self.page == "Assignments":
            fill_table(self.table, [(t["id"], (t["id"], t["vehicle_name"], t["driver_name"], t["route_name"], local_time(t["started_at"]), local_time(t["ended_at"]) if t["ended_at"] else "ACTIVE"), ()) for t in self.data["trips"]])
        elif self.page == "Live monitoring":
            self.vehicle_combo.configure(values=[f"{v['id']} — {v['registration']}" for v in vehicles])
            self.render_monitor()

    def render_monitor(self):
        vehicle = next((v for v in self.data["vehicles"] if v["id"] == self.monitor_id), None)
        if not vehicle:
            return
        trip, sample = vehicle["trip"] or {}, vehicle["sample"] or {}
        state = vehicle_status(vehicle) if self.online else "OFFLINE"
        readings = sample.get("readings", {})
        camera = readings.get("source") == "trained_model"
        missing_speed = (readings.get("speed_method") == "unavailable" or
                         readings.get("assessment_note", "").startswith(("Waiting for phone GPS", "Phone GPS")))
        activity = behavior_label(readings.get("behavior"), readings.get("confidence", 0),
                                  readings.get("face_activity", ""), readings.get("handset_visible")) if camera else "Awaiting camera"
        speed = "Speed unavailable" if missing_speed else f"{readings.get('speed', '—')} km/h"
        if readings.get("speed_method") == "GPS estimate":
            speed += " (estimated)"
        display_state = "Monitoring" if camera and state == "UNKNOWN" else live_status(state, readings)
        self.monitor_heading.configure(text=f"{vehicle['registration']}  •  {display_state}", foreground=COLORS.get(state, "#15283f"))
        details = f"{trip.get('driver_name', 'Unassigned')}  •  {trip.get('route_name', 'No route')}"
        if sample:
            details += f"\n{activity}    •    {speed}"
            prediction = classifier_summary(readings.get("classifier_label"), readings.get("classifier_score", 0), readings.get("handset_visible"))
            if prediction and prediction != activity and not prediction.startswith("Phone-use prediction rejected") and state != "OFFLINE":
                details += f"\nModel prediction: {prediction}"
            if state in ("CAUTION", "HIGH"):
                details += "\n" + sample.get("reason", "")
        self.monitor_details.configure(text=details)
        if state == "OFFLINE":
            self.video.configure(image="", text="Device or server offline. Live camera unavailable.")
            self.video.image = None

    def render_logs(self):
        rows = []
        for entry in self.logs[:8] if self.page == "Overview" else self.logs:
            values = (local_time(entry["captured_at"]), entry["vehicle_name"], entry["driver_name"])
            values += (entry["level"], entry["reason"]) if self.page == "Overview" else (entry["route_name"], entry["level"], entry["score"], entry["reason"])
            rows.append((entry["id"], values, (entry["level"],)))
        fill_table(self.log_table, rows)

    def close(self):
        self.stop.set()
        self.root.destroy()
