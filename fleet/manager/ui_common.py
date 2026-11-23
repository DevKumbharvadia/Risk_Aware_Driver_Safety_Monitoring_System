
"""Shared Tkinter styling and formatting; no business logic."""

from datetime import datetime, timezone
import math
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

VALID_RISK_LEVELS = {
    "LOW",
    "CAUTION",
    "HIGH",
    "UNKNOWN",
}


def enable_high_dpi():
    """Enable Windows high-DPI awareness when supported."""

    if sys.platform != "win32":
        return

    try:
        import ctypes

        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)

        except (AttributeError, OSError):
            try:
                ctypes.windll.user32.SetProcessDPIAware()

            except (AttributeError, OSError):
                pass

    except (AttributeError, OSError):
        pass


def setup_style(root):
    """Configure the shared Tkinter theme and widget styles."""

    root.configure(bg="#eef2f6")

    style = ttk.Style(root)

    if "clam" in style.theme_names():
        style.theme_use("clam")

    style.configure(
        "TFrame",
        background="#eef2f6",
    )

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

    if not isinstance(columns, (tuple, list)) or not columns:
        raise ValueError("Table columns must be a non-empty sequence.")

    if isinstance(height, bool) or not isinstance(height, int) or height <= 0:
        raise ValueError("Table height must be a positive integer.")

    if widths is not None:
        if not isinstance(widths, (tuple, list)):
            raise ValueError("Table widths must be a sequence.")

        for width in widths:
            if (
                isinstance(width, bool)
                or not isinstance(width, (int, float))
                or not math.isfinite(width)
                or width <= 0
            ):
                raise ValueError("Table column widths must be positive.")

    wrapper = ttk.Frame(parent)
    wrapper.pack(
        fill="both",
        expand=True,
        pady=8,
    )

    tree = ttk.Treeview(
        wrapper,
        columns=columns,
        show="headings",
        height=height,
    )

    for index, column in enumerate(columns):

        width = (
            widths[index]
            if widths and index < len(widths)
            else 130
        )

        tree.heading(
            column,
            text=str(column).replace("_", " ").title(),
        )

        tree.column(
            column,
            width=int(width),
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

    tree.grid(
        row=0,
        column=0,
        sticky="nsew",
    )

    vertical.grid(
        row=0,
        column=1,
        sticky="ns",
    )

    horizontal.grid(
        row=1,
        column=0,
        sticky="ew",
    )

    wrapper.rowconfigure(0, weight=1)
    wrapper.columnconfigure(0, weight=1)

    for level, color in COLORS.items():
        tree.tag_configure(
            level,
            foreground=color,
        )

    return tree


def _parse_datetime(value):
    """Parse an ISO timestamp and normalize it to UTC."""

    if not isinstance(value, str) or not value.strip():
        return None

    value = value.strip()

    if value.endswith("Z"):
        value = value[:-1] + "+00:00"

    try:
        parsed = datetime.fromisoformat(value)

        if parsed.tzinfo is None or parsed.utcoffset() is None:
            parsed = parsed.replace(tzinfo=timezone.utc)

        return parsed.astimezone(timezone.utc)

    except (ValueError, TypeError, OverflowError):
        return None


def local_time(value):
    """Convert an ISO timestamp to the computer's local time."""

    if not value:
        return "—"

    parsed = _parse_datetime(value)

    if parsed is None:
        return str(value)

    return parsed.astimezone().strftime(
        "%d %b %H:%M:%S"
    )


def vehicle_status(vehicle):
    """Return a vehicle's current assignment, connection, or risk status."""

    if not isinstance(vehicle, dict):
        return "UNKNOWN"

    if not vehicle.get("trip"):
        return "UNASSIGNED"

    sample = vehicle.get("sample")

    if not isinstance(sample, dict):
        return "OFFLINE"

    captured = _parse_datetime(
        sample.get("captured_at")
    )

    received = _parse_datetime(
        sample.get("received_at")
    )

    if captured is None or received is None:
        return "OFFLINE"

    now = datetime.now(timezone.utc)

    captured_age = (
        now - captured
    ).total_seconds()

    received_age = (
        now - received
    ).total_seconds()

    if (
        captured_age < -5
        or received_age < -5
        or captured_age > OFFLINE_AFTER_SECONDS
        or received_age > OFFLINE_AFTER_SECONDS
    ):
        return "OFFLINE"

    level = str(
        sample.get("level", "UNKNOWN")
    ).strip().upper()

    if level not in VALID_RISK_LEVELS:
        return "UNKNOWN"

    score = sample.get("score")

    if score is not None:
        try:
            if isinstance(score, bool):
                return "UNKNOWN"

            score = float(score)

            if (
                not math.isfinite(score)
                or score < 0
            ):
                return "UNKNOWN"

        except (TypeError, ValueError, OverflowError):
            return "UNKNOWN"

    return level


def fill_table(tree, rows):
    """Update Treeview rows while preserving selection and scroll position."""

    if tree is None:
        return

    if not isinstance(rows, (tuple, list)):
        return

    wanted = set()

    for index, entry in enumerate(rows):

        if not isinstance(entry, (tuple, list)) or len(entry) != 3:
            continue

        row_id, values, tags = entry

        if row_id is None:
            continue

        row_id = str(row_id)

        if not row_id:
            continue

        if row_id in wanted:
            continue

        wanted.add(row_id)

        try:
            values = tuple(values) if values is not None else ()
            tags = tuple(tags) if tags is not None else ()

        except TypeError:
            continue

        if tree.exists(row_id):

            current = tree.item(row_id)

            changed = (
                tuple(current.get("values", ())) != values
                or tuple(current.get("tags", ())) != tags
            )

            if changed:
                tree.item(
                    row_id,
                    values=values,
                    tags=tags,
                )

            children = tree.get_children()

            try:
                current_index = children.index(row_id)

            except ValueError:
                current_index = -1

            if current_index != index:
                tree.move(
                    row_id,
                    "",
                    index,
                )

        else:
            tree.insert(
                "",
                index,
                iid=row_id,
                values=values,
                tags=tags,
            )

    for row_id in tree.get_children():

        if row_id not in wanted:
            tree.delete(row_id)
