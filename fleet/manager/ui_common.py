
"""Shared Tkinter styling and formatting; no business logic."""

from datetime import datetime, timezone
import sys
import tkinter as tk
from tkinter import ttk


COLORS = {
    "LOW": "#16734b",
    "CAUTION": "#956100",
    "HIGH": "#bf293b",
    "UNKNOWN": "#64748b",
    "OFFLINE": "#64748b",
}

OFFLINE_AFTER_SECONDS = 8


def enable_high_dpi():
    """Keep Windows display coordinates and Tk window sizes consistent."""
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass


def setup_style(root):
    """Configure the shared Tkinter theme and widget styles."""
    root.configure(bg="#eef2f6")

    style = ttk.Style(root)
    style.theme_use("clam")

    style.configure("TFrame", background="#eef2f6")
    style.configure(
        "TLabel",
        background="#eef2f6",
        foreground="#15283f",
        font=("Segoe UI", 10),
    )
    style.configure(
        "Title.TLabel",
        font=("Segoe UI", 23, "bold"),
    )
    style.configure(
        "Subtitle.TLabel",
        foreground="#617185",
    )
    style.configure(
        "Metric.TLabel",
        font=("Segoe UI", 17, "bold"),
    )
    style.configure(
        "TButton",
        font=("Segoe UI", 10),
        padding=(12, 7),
    )
    style.configure(
        "Treeview",
        rowheight=31,
        font=("Segoe UI", 10),
        background="white",
        fieldbackground="white",
    )
    style.configure(
        "Treeview.Heading",
        font=("Segoe UI", 10, "bold"),
        padding=7,
    )
    style.map(
        "Treeview",
        background=[("selected", "#dbeafe")],
        foreground=[("selected", "#102e52")],
    )


def make_table(parent, columns, widths=None, height=15):
    """Create a Treeview with vertical and horizontal scrollbars."""
    wrapper = ttk.Frame(parent)
    wrapper.pack(fill="both", expand=True, pady=8)

    tree = ttk.Treeview(
        wrapper,
        columns=columns,
        show="headings",
        height=height,
    )

    for index, column in enumerate(columns):
        width = widths[index] if widths and index < len(widths) else 130

        tree.heading(
            column,
            text=column.replace("_", " ").title(),
        )
        tree.column(
            column,
            width=width,
            minwidth=60,
        )

    vertical = ttk.Scrollbar(
        wrapper,
        orient="vertical",
        command=tree.yview,
    )
    horizontal = ttk.Scrollbar(
        wrapper,
        orient="horizontal",
        command=tree.xview,
    )

    tree.configure(
        yscrollcommand=vertical.set,
        xscrollcommand=horizontal.set,
    )

    tree.grid(row=0, column=0, sticky="nsew")
    vertical.grid(row=0, column=1, sticky="ns")
    horizontal.grid(row=1, column=0, sticky="ew")

    wrapper.rowconfigure(0, weight=1)
    wrapper.columnconfigure(0, weight=1)

    for level, color in COLORS.items():
        tree.tag_configure(level, foreground=color)

    return tree


def _parse_datetime(value):
    """Parse an ISO timestamp and normalize it to UTC."""
    if not isinstance(value, str) or not value.strip():
        return None

    try:
        parsed = datetime.fromisoformat(value)
    except (ValueError, TypeError, OverflowError):
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    return parsed.astimezone(timezone.utc)


def local_time(value):
    """Convert an ISO timestamp to the computer's local time."""
    if not value:
        return "—"

    parsed = _parse_datetime(value)

    if parsed is None:
        return str(value)

    return parsed.astimezone().strftime("%d %b %H:%M:%S")


def vehicle_status(vehicle):
    """Determine whether a vehicle is unassigned, offline, or active."""
    if not isinstance(vehicle, dict):
        return "UNKNOWN"

    if not vehicle.get("trip"):
        return "UNASSIGNED"

    sample = vehicle.get("sample")

    if not isinstance(sample, dict):
        return "OFFLINE"

    captured = _parse_datetime(sample.get("captured_at"))
    received = _parse_datetime(sample.get("received_at"))

    if captured is None or received is None:
        return "OFFLINE"

    now = datetime.now(timezone.utc)

    captured_age = (now - captured).total_seconds()
    received_age = (now - received).total_seconds()

    if (
        captured_age > OFFLINE_AFTER_SECONDS
        or received_age > OFFLINE_AFTER_SECONDS
    ):
        return "OFFLINE"

    return sample.get("level") or "UNKNOWN"


def fill_table(tree, rows):
    """Update values without destroying the current selection or scroll position."""
    wanted = set()

    for index, (row_id, values, tags) in enumerate(rows):
        row_id = str(row_id)
        wanted.add(row_id)

        if tree.exists(row_id):
            tree.item(
                row_id,
                values=values,
                tags=tags,
            )
        else:
            tree.insert(
                "",
                "end",
                iid=row_id,
                values=values,
                tags=tags,
            )

        tree.move(row_id, "", index)

    for row_id in tree.get_children():
        if row_id not in wanted:
            tree.delete(row_id)
