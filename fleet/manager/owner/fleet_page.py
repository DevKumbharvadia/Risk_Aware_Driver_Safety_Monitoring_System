
"""Fleet, driver, route and trip management."""

import tkinter as tk
from tkinter import ttk, messagebox

from ..ui_common import make_table, fill_table, vehicle_status
from .dashboard_page import live_status


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


class FleetPageMixin:

    def build_fleet(self):
        notebook = ttk.Notebook(self.content)
        notebook.pack(fill="both", expand=True)
        self.fleet_notebook = notebook

        tabs = (
            ("vehicles", "Vehicles", ("id", "registration", "model", "driver", "route", "status")),
            ("drivers", "Drivers", ("id", "name", "license", "phone", "vehicle", "status")),
            ("routes", "Routes", ("id", "name", "origin", "destination")),
            ("trips", "Assignments", ("id", "vehicle", "driver", "route", "started", "ended")),
        )

        for kind, title, columns in tabs:
            frame = ttk.Frame(notebook, padding=10)
            notebook.add(frame, text=title)

            toolbar = ttk.Frame(frame)
            toolbar.pack(fill="x", pady=(0, 8))

            if kind in ENTITY_FIELDS:
                actions = (
                    ("Add", lambda k=kind: self.entity_dialog(k)),
                    ("Edit", lambda k=kind: self.edit_selected(k)),
                    ("Delete", lambda k=kind: self.delete_selected(k)),
                )
            else:
                actions = (
                    ("Assign / change trip", self.assignment_dialog),
                    ("End selected trip", self.end_selected_trip),
                )

            for label, action in actions:
                ttk.Button(toolbar, text=label, command=action).pack(
                    side="left", padx=(0, 6)
                )

            self.tables[kind] = make_table(frame, columns, height=16)

            if kind in ("vehicles", "drivers"):
                self.tables[kind].bind(
                    "<Double-1>",
                    lambda event, k=kind: self.open_live_from_fleet(k),
                )

            if kind == "trips":
                ttk.Label(
                    frame,
                    text="Changing an assignment ends the previous trip and keeps its history.",
                ).pack(anchor="w", pady=(6, 0))

        notebook.bind("<<NotebookTabChanged>>", self.fleet_tab_changed)

    def fleet_tab_changed(self, _event=None):
        self.fleet_tab = (
            "vehicles", "drivers", "routes", "trips"
        )[self.fleet_notebook.index(self.fleet_notebook.select())]

    def selected_id(self, kind):
        table = self.tables.get(kind)
        selected = table.selection() if table else ()

        if not selected:
            messagebox.showinfo(
                "Select a record", "Select a row first.", parent=self.root
            )
            return None

        try:
            return int(selected[0])
        except (ValueError, TypeError):
            return None

    def edit_selected(self, kind):
        record_id = self.selected_id(kind)
        if record_id is None:
            return

        record = next(
            (item for item in self.data[kind] if item["id"] == record_id),
            None,
        )

        if record:
            self.entity_dialog(kind, record)

    def delete_selected(self, kind):
        record_id = self.selected_id(kind)
        if record_id is None:
            return

        if messagebox.askyesno(
            "Confirm deletion",
            f"Delete this {ENTITY_NAMES[kind]}?",
            parent=self.root,
        ):
            self.submit(
                "/delete-entity",
                {"kind": kind, "id": record_id},
                lambda _: self.refresh_after_change(),
            )

    def entity_dialog(self, kind, record=None):
        dialog = tk.Toplevel(self.root)
        dialog.title(
            ("Edit " if record else "Add ") + ENTITY_NAMES[kind]
        )
        dialog.transient(self.root)
        dialog.grab_set()

        frame = ttk.Frame(dialog, padding=22)
        frame.pack(fill="both", expand=True)

        entries = {}

        for index, field in enumerate(ENTITY_FIELDS[kind]):
            ttk.Label(
                frame,
                text=field.replace("_", " ").title(),
            ).grid(row=index, column=0, sticky="w", padx=(0, 18), pady=8)

            variable = tk.StringVar(
                value=record.get(field, "") if record else ""
            )

            ttk.Entry(
                frame, textvariable=variable, width=36
            ).grid(row=index, column=1, pady=8)

            entries[field] = variable

        def save():
            values = {
                field: variable.get().strip()
                for field, variable in entries.items()
            }

            if not all(values.values()):
                messagebox.showwarning(
                    "Missing information",
                    "Please fill in all fields.",
                    parent=dialog,
                )
                return

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
            frame, text="Save", command=save
        ).grid(row=len(entries), column=1, sticky="e", pady=(12, 0))

        dialog.bind("<Return>", lambda _: save())

    def refresh_after_change(self):
        self.submit("/snapshot", None, self.update_snapshot)

    def update_snapshot(self, result):
        self.data = result
        self.render_data()

    def assignment_dialog(self):
        kinds = (
            ("vehicles", "registration"),
            ("drivers", "name"),
            ("routes", "name"),
        )

        if any(not self.data[kind] for kind, _ in kinds):
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

        for index, (kind, field) in enumerate(kinds):
            ttk.Label(
                frame,
                text=ENTITY_NAMES[kind].title(),
            ).grid(row=index, column=0, sticky="w", padx=(0, 14), pady=9)

            combo = ttk.Combobox(
                frame,
                state="readonly",
                width=38,
                values=[
                    f'{item["id"]} — {item[field]}'
                    for item in self.data[kind]
                ],
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
            frame, text="Start trip", command=save
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
                lambda _: self.refresh_after_change(),
            )

    def open_live_from_fleet(self, kind):
        record_id = self.selected_id(kind)
        if record_id is None:
            return

        if kind == "drivers":
            vehicle = next(
                (
                    v for v in self.data["vehicles"]
                    if v.get("trip")
                    and v["trip"]["driver_id"] == record_id
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
            self.monitor_session_id = None
            self.latest_preview = None

        self.render_data()

    def render_fleet(self):
        vehicles = self.data["vehicles"]
        drivers = self.data["drivers"]

        active_drivers = {
            v["trip"]["driver_id"]: v
            for v in vehicles if v.get("trip")
        }

        rows_by_kind = {
            "vehicles": [],
            "drivers": [],
            "routes": [],
            "trips": [],
        }

        for v in vehicles:
            trip = v.get("trip") or {}
            sample = v.get("sample") or {}
            status = vehicle_status(v) if self.online else "OFFLINE"

            rows_by_kind["vehicles"].append((
                v["id"],
                (
                    v["id"], v["registration"], v["model"],
                    trip.get("driver_name", "—"),
                    trip.get("route_name", "—"),
                    live_status(status, sample.get("readings") or {})
                    if self.online else "OFFLINE",
                ),
                (status,),
            ))

        for d in drivers:
            vehicle = active_drivers.get(d["id"])
            status = (
                vehicle_status(vehicle) if self.online else "OFFLINE"
            ) if vehicle else "NO TRIP"

            rows_by_kind["drivers"].append((
                d["id"],
                (
                    d["id"], d["name"], d["license"], d["phone"],
                    vehicle["registration"] if vehicle else "—",
                    status,
                ),
                (),
            ))

        for r in self.data["routes"]:
            rows_by_kind["routes"].append((
                r["id"],
                (r["id"], r["name"], r["origin"], r["destination"]),
                (),
            ))

        for t in self.data["trips"]:
            rows_by_kind["trips"].append((
                t["id"],
                (
                    t["id"], t["vehicle_name"], t["driver_name"],
                    t["route_name"], self.local_time(t["started_at"]),
                    self.local_time(t["ended_at"]) if t["ended_at"] else "ACTIVE",
                ),
                (),
            ))

        for kind, rows in rows_by_kind.items():
            fill_table(self.tables[kind], rows)
