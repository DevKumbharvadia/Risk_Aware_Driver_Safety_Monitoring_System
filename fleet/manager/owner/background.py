
"""Background API and camera preview workers."""

import queue
import time

from ..network import ApiError


PREVIEW_INTERVAL = 0.05
PREVIEW_ERROR_RETRY = 0.5
UI_POLL_INTERVAL = 30
BACKGROUND_INTERVAL = 1.0
MAX_COMMANDS_PER_CYCLE = 50


class BackgroundMixin:

    def worker(self):
        """Process API commands and refresh dashboard data."""

        while not self.stop.is_set():
            for _ in range(MAX_COMMANDS_PER_CYCLE):
                if self.stop.is_set():
                    break

                try:
                    path, payload, callback = self.commands.get_nowait()
                except queue.Empty:
                    break

                try:
                    result = self.api.request(path, payload)
                    self.events.put(("done", (callback, result)))
                except ApiError as error:
                    self.events.put(("error", str(error)))

            if self.stop.is_set():
                break

            try:
                self.events.put((
                    "snapshot",
                    self.api.request("/snapshot"),
                ))

                with self.selection_lock:
                    query = self.log_query
                    session_id = (
                        self.monitor_session_id
                        if self.page == "Dashboard"
                        else None
                    )

                self.events.put((
                    "logs",
                    self.api.request("/logs" + query),
                ))

                self.api.request(
                    "/preview-selection",
                    {"session_id": session_id},
                )

            except ApiError as error:
                self.events.put(("offline", str(error)))

            self.stop.wait(BACKGROUND_INTERVAL)

    def preview_worker(self):
        """Retrieve the latest frame from the selected phone."""

        last_session_id = None

        while not self.stop.is_set():
            with self.selection_lock:
                session_id = (
                    self.monitor_session_id
                    if self.page == "Dashboard"
                    else None
                )

                if session_id != last_session_id:
                    self.latest_preview = None
                    last_session_id = session_id

            if session_id is None:
                self.stop.wait(0.1)
                continue

            started = time.monotonic()

            try:
                frame = self.api.request(
                    f"/frame/{session_id}",
                    raw=True,
                )

                if self.stop.is_set():
                    break

                with self.selection_lock:
                    current = (
                        self.monitor_session_id
                        if self.page == "Dashboard"
                        else None
                    )

                    if current == session_id and frame:
                        self.latest_preview = (session_id, frame, "")

                self.stop.wait(max(
                    0,
                    PREVIEW_INTERVAL - (time.monotonic() - started),
                ))

            except ApiError as error:
                if self.stop.is_set():
                    break

                with self.selection_lock:
                    current = (
                        self.monitor_session_id
                        if self.page == "Dashboard"
                        else None
                    )

                    if current == session_id:
                        self.latest_preview = (
                            session_id,
                            None,
                            str(error),
                        )

                self.stop.wait(PREVIEW_ERROR_RETRY)

    def drain_events(self):
        """Process events and display the newest camera frame."""

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

                if self.page == "Dashboard":
                    self.update_monitor_sessions()

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
                from tkinter import messagebox
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
            selected = (
                self.monitor_session_id
                if self.page == "Dashboard"
                else None
            )

        if (
            preview
            and selected is not None
            and str(preview[0]) == str(selected)
        ):
            if preview[1]:
                self.render_frame(preview[0], preview[1])
            elif hasattr(self, "video"):
                self.video.configure(
                    image="",
                    text="Selected phone camera is not currently available.",
                )
                self.video.image = None

        self.root.after(UI_POLL_INTERVAL, self.drain_events)

    def submit(self, path, payload=None, callback=None):
        """Queue an API request."""
        self.commands.put((path, payload, callback))

    def render_data(self):
        """Render the active page."""

        if not self.online and not any(self.data.values()):
            return

        pages = {
            "Dashboard": self.render_dashboard,
            "Fleet management": self.render_fleet,
            "Reports": self.render_reports,
            "Phone connections": self.render_phone_connections,
        }

        render = pages.get(self.page)
        if render:
            render()

    def close(self):
        """Stop workers and close the application."""

        self.stop.set()

        try:
            self.api.request(
                "/preview-selection",
                {"session_id": None},
            )
        except ApiError:
            pass

        try:
            self.root.destroy()
        except Exception:
            pass
