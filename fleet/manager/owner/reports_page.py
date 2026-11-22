
"""Reports, filters and CSV export."""

import csv
from datetime import datetime, time, timezone
from tkinter import ttk, filedialog, messagebox
from urllib.parse import urlencode

from ..ui_common import make_table, fill_table, local_time


class ReportsPageMixin:

    def build_reports(self):
        controls = ttk.Frame(self.content)
        controls.pack(fill="x")

        self.filters = {}

        options = (
            ("Vehicle", "vehicle_id", [
                "ALL",
                *[
                    f'{v["id"]} — {v["registration"]}'
                    for v in self.data["vehicles"]
                ],
            ]),
            ("Driver", "driver_id", [
                "ALL",
                *[
                    f'{d["id"]} — {d["name"]}'
                    for d in self.data["drivers"]
                ],
            ]),
            ("Risk", "level", [
                "ALL", "LOW", "CAUTION", "HIGH", "UNKNOWN"
            ]),
        )

        for column, (label, key, values) in enumerate(options):
            ttk.Label(controls, text=label).grid(
                row=0, column=column, sticky="w"
            )

            combo = ttk.Combobox(
                controls, state="readonly", values=values, width=23
            )
            combo.grid(
                row=1, column=column, sticky="w",
                padx=(0, 10), pady=5,
            )
            combo.current(0)
            self.filters[key] = combo

        for column, key, label in (
            (0, "since", "From date (YYYY-MM-DD)"),
            (1, "until", "To date (YYYY-MM-DD)"),
        ):
            ttk.Label(controls, text=label).grid(
                row=2, column=column, sticky="w"
            )

            entry = ttk.Entry(controls, width=25)
            entry.grid(
                row=3, column=column, sticky="w",
                padx=(0, 10), pady=5,
            )
            self.filters[key] = entry

        ttk.Button(
            controls, text="Apply filters", command=self.apply_filters
        ).grid(row=3, column=2, sticky="w", padx=6)

        ttk.Button(
            controls, text="Export CSV", command=self.export_logs
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

                if not value or value == "ALL":
                    continue

                if key in ("since", "until"):
                    date = datetime.strptime(value, "%Y-%m-%d").date()
                    bound = time.min if key == "since" else time.max

                    value = datetime.combine(
                        date, bound
                    ).astimezone().astimezone(
                        timezone.utc
                    ).isoformat(timespec="milliseconds")

                elif key in ("vehicle_id", "driver_id"):
                    value = value.split(" — ", 1)[0]

                filters[key] = value

            if filters.get("since", "") > filters.get("until", "9999"):
                raise ValueError(
                    "Start date must not be after end date."
                )

        except ValueError as error:
            messagebox.showerror(
                "Invalid filter", str(error), parent=self.root
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
            with open(path, "w", newline="", encoding="utf-8-sig") as handle:
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
                "Export failed", str(error), parent=self.root
            )
            return

        messagebox.showinfo(
            "Export complete",
            f"Saved {len(self.logs)} events.",
            parent=self.root,
        )

    def render_reports(self):
        table = self.tables.get("reports")
        if table is None:
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

        fill_table(table, rows)
        self.report_summary.configure(
            text=(
                f"Showing {len(self.logs)} matching risk transitions "
                "(maximum 1,000)."
            )
        )
