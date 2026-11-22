"""Shared Tkinter styling and formatting; no business logic."""
from datetime import datetime, timezone
import tkinter as tk
from tkinter import ttk

COLORS = {"LOW": "#16734b", "CAUTION": "#956100", "HIGH": "#bf293b", "UNKNOWN": "#64748b", "OFFLINE": "#64748b"}


def enable_high_dpi():
    """Keep Windows display coordinates and Tk window sizes consistent."""
    import sys
    if sys.platform == "win32":
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass


def setup_style(root):
    root.configure(bg="#eef2f6")
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure("TFrame", background="#eef2f6")
    style.configure("TLabel", background="#eef2f6", foreground="#15283f", font=("Segoe UI", 10))
    style.configure("Title.TLabel", font=("Segoe UI", 23, "bold"))
    style.configure("Subtitle.TLabel", foreground="#617185")
    style.configure("Metric.TLabel", font=("Segoe UI", 17, "bold"))
    style.configure("TButton", font=("Segoe UI", 10), padding=(12, 7))
    style.configure("Treeview", rowheight=31, font=("Segoe UI", 10), background="white", fieldbackground="white")
    style.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"), padding=7)
    style.map("Treeview", background=[("selected", "#dbeafe")], foreground=[("selected", "#102e52")])


def make_table(parent, columns, widths=None, height=15):
    wrapper = ttk.Frame(parent)
    wrapper.pack(fill="both", expand=True, pady=8)
    tree = ttk.Treeview(wrapper, columns=columns, show="headings", height=height)
    for index, column in enumerate(columns):
        tree.heading(column, text=column.replace("_", " ").title())
        tree.column(column, width=widths[index] if widths else 130, minwidth=60)
    vertical = ttk.Scrollbar(wrapper, orient="vertical", command=tree.yview)
    horizontal = ttk.Scrollbar(wrapper, orient="horizontal", command=tree.xview)
    tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
    tree.grid(row=0, column=0, sticky="nsew")
    vertical.grid(row=0, column=1, sticky="ns")
    horizontal.grid(row=1, column=0, sticky="ew")
    wrapper.rowconfigure(0, weight=1)
    wrapper.columnconfigure(0, weight=1)
    for level, color in COLORS.items():
        tree.tag_configure(level, foreground=color)
    return tree


def local_time(value):
    if not value:
        return "—"
    try:
        return datetime.fromisoformat(value).astimezone().strftime("%d %b %H:%M:%S")
    except ValueError:
        return value


def vehicle_status(vehicle):
    sample = vehicle.get("sample")
    if not vehicle.get("trip"):
        return "UNASSIGNED"
    if not sample:
        return "OFFLINE"
    captured = datetime.fromisoformat(sample["captured_at"])
    received = datetime.fromisoformat(sample["received_at"])
    now = datetime.now(timezone.utc)
    if (now - captured).total_seconds() > 8 or (now - received).total_seconds() > 8:
        return "OFFLINE"
    return sample["level"]


def fill_table(tree, rows):
    """Update values without destroying the current selection or scroll position."""
    wanted = set()
    for index, (row_id, values, tags) in enumerate(rows):
        row_id = str(row_id)
        wanted.add(row_id)
        if tree.exists(row_id):
            tree.item(row_id, values=values, tags=tags)
        else:
            tree.insert("", "end", iid=row_id, values=values, tags=tags)
        tree.move(row_id, "", index)
    for row_id in tree.get_children():
        if row_id not in wanted:
            tree.delete(row_id)
