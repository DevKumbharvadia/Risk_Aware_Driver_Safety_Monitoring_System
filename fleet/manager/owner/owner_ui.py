
"""Main Fleet Guardian owner application."""

import queue
import threading
import tkinter as tk
from tkinter import ttk

from ..ui_common import setup_style

from .dashboard_page import DashboardPageMixin
from .phone_page import PhonePageMixin
from .fleet_page import FleetPageMixin
from .reports_page import ReportsPageMixin
from .background import BackgroundMixin


class OwnerApp(
    DashboardPageMixin,
    PhonePageMixin,
    FleetPageMixin,
    ReportsPageMixin,
    BackgroundMixin,
):

    PAGES = {
        "Dashboard": "build_dashboard",
        "Fleet management": "build_fleet",
        "Reports": "build_reports",
        "Phone connections": "build_phone_connections",
    }

    def __init__(
        self,
        root,
        api,
        public_url="",
        phone_link_provider=None,
        create_phone_link_provider=None,
        phone_sessions_provider=None,
    ):
        self.root = root
        self.api = api
        self.public_url = public_url.rstrip("/")

        self.phone_link_provider = phone_link_provider
        self.create_phone_link_provider = create_phone_link_provider
        self.phone_sessions_provider = phone_sessions_provider

        self.data = {
            key: [] for key in ("vehicles", "drivers", "routes", "trips")
        }

        self.logs = []
        self.events = queue.Queue()
        self.commands = queue.Queue()
        self.stop = threading.Event()
        self.selection_lock = threading.Lock()

        self.monitor_id = None
        self.monitor_session_id = None
        self.latest_preview = None

        self.log_query = ""
        self.page = "Dashboard"
        self.online = False

        self.tables = {}
        self.filters = {}

        self.phone_table = None
        self.phone_links = {}
        self.phone_sessions = {}
        self.session_labels = {}

        self.configure_window()
        self.build_shell()
        self.show_page("Dashboard")

        self.root.protocol("WM_DELETE_WINDOW", self.close)

        self.start_worker(self.worker, "fleet-api-worker")
        self.start_worker(self.preview_worker, "fleet-preview-worker")

        self.root.after(100, self.drain_events)

    def configure_window(self):
        self.root.title("Fleet Guardian")
        self.root.geometry("1260x790")
        self.root.minsize(980, 640)
        setup_style(self.root)

    def start_worker(self, target, name):
        threading.Thread(
            target=target,
            name=name,
            daemon=True,
        ).start()

    def build_shell(self):
        header = tk.Frame(
            self.root,
            bg="#14283f",
            height=76,
        )
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

        for name in self.PAGES:
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
        builder_name = self.PAGES.get(name)

        if builder_name is None:
            raise ValueError(f"Unknown page: {name}")

        self.page = name
        self.page_title.configure(text=name)

        for label, button in self.nav_buttons.items():
            button.configure(
                state="disabled" if label == name else "normal"
            )

        for child in self.content.winfo_children():
            child.destroy()

        self.tables.clear()
        self.phone_table = None

        with self.selection_lock:
            if name != "Dashboard":
                self.monitor_id = None
                self.monitor_session_id = None
                self.latest_preview = None

            if name != "Reports":
                self.log_query = ""

        getattr(self, builder_name)()
        self.render_data()
