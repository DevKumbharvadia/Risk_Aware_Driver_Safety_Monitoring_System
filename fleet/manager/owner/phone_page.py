
"""Phone connection and session management."""

import tkinter as tk
from tkinter import ttk, messagebox


class PhonePageMixin:

    def get_phone_link(self, vehicle_id):
        if not self.phone_link_provider:
            return ""

        try:
            return self.phone_link_provider(vehicle_id) or ""
        except Exception:
            return ""

    def create_phone_link(self, vehicle_id):
        if not self.create_phone_link_provider:
            return ""

        try:
            return self.create_phone_link_provider(vehicle_id) or ""
        except Exception as error:
            messagebox.showerror(
                "Could not create phone link",
                str(error),
                parent=self.root,
            )
            return ""

    def get_phone_sessions(self, vehicle_id):
        if not self.phone_sessions_provider:
            return []

        try:
            return list(self.phone_sessions_provider(vehicle_id) or [])
        except Exception:
            return []

    @staticmethod
    def session_id_of(session):
        if isinstance(session, dict):
            return session.get("session_id") or session.get("id")
        return getattr(session, "session_id", None)

    @staticmethod
    def session_link_of(session):
        if isinstance(session, dict):
            return session.get("link", "")
        return getattr(session, "link", "")

    @staticmethod
    def session_created_of(session):
        if isinstance(session, dict):
            return session.get("created_at", "")
        return getattr(session, "created_at", "")

    @staticmethod
    def session_last_seen_of(session):
        if isinstance(session, dict):
            return session.get("last_seen", "")
        return getattr(session, "last_seen", "")

    def refresh_phone_session_cache(self):
        sessions_by_vehicle = {}
        links = {}

        for vehicle in self.data.get("vehicles", []):
            vehicle_id = vehicle.get("id")
            if vehicle_id is None:
                continue

            sessions = self.get_phone_sessions(vehicle_id)

            if not sessions:
                link = self.get_phone_link(vehicle_id)
                if link:
                    sessions = [{
                        "session_id": f"primary-{vehicle_id}",
                        "link": link,
                    }]

            sessions_by_vehicle[vehicle_id] = sessions

            for session in sessions:
                session_id = self.session_id_of(session)
                if session_id is not None:
                    links[str(session_id)] = self.session_link_of(session)

        self.phone_sessions = sessions_by_vehicle
        self.phone_links = links

    def session_display_name(self, vehicle_id, session_id):
        for index, session in enumerate(
            self.phone_sessions.get(vehicle_id, []), 1
        ):
            if str(self.session_id_of(session)) == str(session_id):
                return f"Phone {index}"

        return "Phone"

    def sessions_for_vehicle(self, vehicle_id):
        return [
            session
            for session in self.phone_sessions.get(vehicle_id, [])
            if self.session_id_of(session)
        ]

    def build_phone_connections(self):
        ttk.Label(
            self.content,
            text="Connect driver smartphones",
            style="Metric.TLabel",
        ).pack(anchor="w", pady=(0, 6))

        ttk.Label(
            self.content,
            text=(
                "Each phone gets its own unique connection session. "
                "Create a separate link for every phone."
            ),
            style="Subtitle.TLabel",
            wraplength=950,
        ).pack(anchor="w", pady=(0, 14))

        if not self.public_url:
            ttk.Label(
                self.content,
                text="Cloudflare public URL is not available.",
            ).pack(anchor="w")
            return

        url_frame = ttk.LabelFrame(
            self.content,
            text="Public phone service",
            padding=12,
        )
        url_frame.pack(fill="x", pady=(0, 14))

        self.public_url_var = tk.StringVar(value=self.public_url)

        ttk.Entry(
            url_frame,
            textvariable=self.public_url_var,
            state="readonly",
            width=100,
        ).pack(side="left", fill="x", expand=True, padx=(0, 8))

        ttk.Button(
            url_frame,
            text="Copy public URL",
            command=lambda: self.copy_text(self.public_url),
        ).pack(side="left")

        toolbar = ttk.Frame(self.content)
        toolbar.pack(fill="x", pady=(0, 8))

        buttons = (
            ("Refresh sessions", self.render_phone_connections),
            ("Create another phone link", self.create_selected_phone_link),
            ("Copy selected phone link", self.copy_selected_phone_link),
        )

        for index, (label, action) in enumerate(buttons):
            ttk.Button(
                toolbar,
                text=label,
                command=action,
            ).pack(side="left", padx=(0, 8) if index == 0 else 0)

        ttk.Label(
            self.content,
            text="Phone camera sessions",
            style="Metric.TLabel",
        ).pack(anchor="w", pady=(6, 8))

        table_frame = ttk.Frame(self.content)
        table_frame.pack(fill="both", expand=True)

        columns = (
            ("vehicle", "Vehicle", 140),
            ("driver", "Assigned driver", 160),
            ("route", "Route", 160),
            ("session", "Phone session", 100),
            ("link", "Phone connection", 420),
        )

        self.phone_table = ttk.Treeview(
            table_frame,
            columns=tuple(column[0] for column in columns),
            show="headings",
            height=16,
        )

        for column, heading, width in columns:
            self.phone_table.heading(column, text=heading)
            self.phone_table.column(column, width=width, anchor="w")

        scrollbar = ttk.Scrollbar(
            table_frame,
            orient="vertical",
            command=self.phone_table.yview,
        )

        self.phone_table.configure(yscrollcommand=scrollbar.set)
        self.phone_table.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self.phone_table.bind(
            "<Double-1>",
            self.copy_selected_phone_link,
        )

        self.render_phone_connections()

    def render_phone_connections(self):
        table = self.phone_table

        if table is None or not table.winfo_exists():
            return

        selected = table.selection()
        selected_id = selected[0] if selected else None

        table.delete(*table.get_children())
        self.refresh_phone_session_cache()

        for vehicle in self.data.get("vehicles", []):
            vehicle_id = vehicle.get("id")
            if vehicle_id is None:
                continue

            trip = vehicle.get("trip") or {}

            for index, session in enumerate(
                self.sessions_for_vehicle(vehicle_id), 1
            ):
                session_id = self.session_id_of(session)
                if session_id is None:
                    continue

                iid = f"session-{vehicle_id}-{session_id}"
                link = self.session_link_of(session) or ""

                table.insert(
                    "",
                    "end",
                    iid=iid,
                    values=(
                        vehicle.get("registration", "—"),
                        trip.get("driver_name", "Unassigned"),
                        trip.get("route_name", "Unassigned"),
                        f"Phone {index}",
                        link or "Link unavailable",
                    ),
                )

                self.phone_links[iid] = link

        if selected_id and table.exists(selected_id):
            table.selection_set(selected_id)

    def create_selected_phone_link(self):
        vehicles = self.data.get("vehicles", [])

        if not vehicles:
            messagebox.showinfo(
                "No vehicles",
                "Add a vehicle before creating a phone link.",
                parent=self.root,
            )
            return

        selected = (
            self.phone_table.selection()
            if self.phone_table else ()
        )

        vehicle = None

        if selected:
            values = self.phone_table.item(selected[0], "values")
            registration = values[0] if values else ""

            vehicle = next(
                (
                    item for item in vehicles
                    if item.get("registration") == registration
                ),
                None,
            )

        if vehicle:
            self.create_phone_link_for_vehicle(vehicle["id"])
        elif len(vehicles) == 1:
            self.create_phone_link_for_vehicle(vehicles[0]["id"])
        else:
            self.choose_vehicle_for_phone_link(vehicles)

    def choose_vehicle_for_phone_link(self, vehicles):
        dialog = tk.Toplevel(self.root)
        dialog.title("Choose vehicle")
        dialog.transient(self.root)
        dialog.grab_set()

        frame = ttk.Frame(dialog, padding=18)
        frame.pack(fill="both", expand=True)

        ttk.Label(
            frame,
            text="Select the vehicle for the new phone:",
        ).pack(anchor="w", pady=(0, 8))

        choices = [
            f'{item["id"]} — {item["registration"]}'
            for item in vehicles
        ]

        combo = ttk.Combobox(
            frame,
            state="readonly",
            values=choices,
            width=40,
        )
        combo.pack(fill="x")
        combo.current(0)

        def create():
            try:
                vehicle_id = int(combo.get().split(" — ", 1)[0])
            except (ValueError, IndexError):
                messagebox.showerror(
                    "Invalid selection",
                    "Choose a valid vehicle.",
                    parent=dialog,
                )
                return

            dialog.destroy()
            self.create_phone_link_for_vehicle(vehicle_id)

        ttk.Button(
            frame,
            text="Create phone link",
            command=create,
        ).pack(anchor="e", pady=(12, 0))

    def create_phone_link_for_vehicle(self, vehicle_id):
        link = self.create_phone_link(vehicle_id)

        if not link:
            messagebox.showerror(
                "Link unavailable",
                "The server could not create a new phone session.",
                parent=self.root,
            )
            return

        self.render_phone_connections()
        self.copy_text(link)

    def copy_selected_phone_link(self, _event=None):
        table = self.phone_table

        if table is None or not table.winfo_exists():
            return

        selected = table.selection()

        if not selected:
            messagebox.showinfo(
                "Select a phone",
                "Select a phone session first.",
                parent=self.root,
            )
            return

        self.copy_text(self.phone_links.get(selected[0], ""))

    def copy_text(self, value):
        if not value:
            messagebox.showwarning(
                "Link unavailable",
                "The phone connection link is not available.",
                parent=self.root,
            )
            return

        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(value)
            self.root.update_idletasks()
        except tk.TclError:
            messagebox.showerror(
                "Clipboard error",
                "Could not copy the link to the clipboard.",
                parent=self.root,
            )
            return

        messagebox.showinfo(
            "Copied",
            "Phone connection link copied to clipboard.",
            parent=self.root,
        )
