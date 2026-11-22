
"""SQLite persistence. Each operation owns its connection (safe across threads)."""

from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3


ENTITY_FIELDS = {
    "drivers": ("name", "license", "phone"),
    "vehicles": ("registration", "model"),
    "routes": ("name", "origin", "destination"),
}


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

        with self.connection() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;

                CREATE TABLE IF NOT EXISTS drivers (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    license TEXT NOT NULL UNIQUE,
                    phone TEXT NOT NULL DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS vehicles (
                    id INTEGER PRIMARY KEY,
                    registration TEXT NOT NULL UNIQUE,
                    model TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS routes (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    origin TEXT NOT NULL,
                    destination TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS trips (
                    id INTEGER PRIMARY KEY,
                    vehicle_id INTEGER NOT NULL REFERENCES vehicles(id),
                    driver_id INTEGER NOT NULL REFERENCES drivers(id),
                    route_id INTEGER NOT NULL REFERENCES routes(id),
                    started_at TEXT NOT NULL,
                    ended_at TEXT,
                    driver_name TEXT NOT NULL,
                    vehicle_name TEXT NOT NULL,
                    route_name TEXT NOT NULL
                );

                CREATE UNIQUE INDEX IF NOT EXISTS active_vehicle
                ON trips(vehicle_id) WHERE ended_at IS NULL;

                CREATE UNIQUE INDEX IF NOT EXISTS active_driver
                ON trips(driver_id) WHERE ended_at IS NULL;

                CREATE TABLE IF NOT EXISTS samples (
                    id TEXT PRIMARY KEY,
                    trip_id INTEGER NOT NULL REFERENCES trips(id),
                    captured_at TEXT NOT NULL,
                    received_at TEXT NOT NULL,
                    score INTEGER NOT NULL,
                    level TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    readings TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS sample_trip_time
                ON samples(trip_id, captured_at);

                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY,
                    sample_id TEXT UNIQUE REFERENCES samples(id),
                    trip_id INTEGER NOT NULL REFERENCES trips(id),
                    captured_at TEXT NOT NULL,
                    level TEXT NOT NULL,
                    score INTEGER NOT NULL,
                    reason TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS event_time
                ON events(captured_at);

                CREATE INDEX IF NOT EXISTS event_trip
                ON events(trip_id);
            """)

    @contextmanager
    def connection(self):
        db = sqlite3.connect(
            self.path,
            timeout=10,
        )
        db.row_factory = sqlite3.Row

        try:
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("PRAGMA busy_timeout=10000")

            with db:
                yield db

        finally:
            db.close()

    # ---------------------------------------------------------
    # Initial data
    # ---------------------------------------------------------

    def seed(self):
        """Insert demonstration records only into an empty database."""
        with self.connection() as db:
            counts = {
                table: db.execute(
                    f"SELECT COUNT(*) FROM {table}"
                ).fetchone()[0]
                for table in ("vehicles", "drivers", "routes")
            }

            # Do not partially seed an existing database.
            if any(counts.values()):
                return

            drivers = (
                ("Aarav Shah", "LIC-001", "Contact"),
                ("Meera Patel", "LIC-002", "Contact"),
                ("Kabir Desai", "LIC-003", "Contact"),
            )

            destinations = (
                "Campus",
                "Station",
                "Warehouse",
            )

            for index, (name, license_number, phone) in enumerate(
                drivers,
                start=1,
            ):
                vehicle = f"VEH-{index:03}"
                route = f"Route {index}"

                db.execute(
                    """
                    INSERT INTO drivers(name, license, phone)
                    VALUES (?, ?, ?)
                    """,
                    (name, license_number, phone),
                )

                db.execute(
                    """
                    INSERT INTO vehicles(registration, model)
                    VALUES (?, ?)
                    """,
                    (vehicle, "Lab vehicle"),
                )

                db.execute(
                    """
                    INSERT INTO routes(name, origin, destination)
                    VALUES (?, ?, ?)
                    """,
                    (route, "Depot", destinations[index - 1]),
                )

                db.execute(
                    """
                    INSERT INTO trips(
                        vehicle_id,
                        driver_id,
                        route_id,
                        started_at,
                        driver_name,
                        vehicle_name,
                        route_name
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        index,
                        index,
                        index,
                        utc_now(),
                        name,
                        vehicle,
                        route,
                    ),
                )

    # ---------------------------------------------------------
    # Entity management
    # ---------------------------------------------------------

    def save_entity(self, kind, values):
        if kind not in ENTITY_FIELDS:
            raise ValueError("Unknown record type.")

        if not isinstance(values, dict):
            raise ValueError("Invalid record data.")

        fields = ENTITY_FIELDS[kind]
        cleaned = []

        for field in fields:
            value = values.get(field, "")

            if not isinstance(value, str):
                raise ValueError(
                    f"Enter a valid {field}."
                )

            value = value.strip()

            if len(value) > 100:
                raise ValueError(
                    f"{field.title()} must not exceed 100 characters."
                )

            if not value and field != "phone":
                raise ValueError(
                    f"{field.replace('_', ' ').title()} is required."
                )

            cleaned.append(value)

        record_id = values.get("id")

        with self.connection() as db:
            if record_id is not None:
                if isinstance(record_id, bool):
                    raise ValueError("Invalid record ID.")

                try:
                    record_id = int(record_id)
                except (TypeError, ValueError):
                    raise ValueError("Invalid record ID.")

                if record_id <= 0:
                    raise ValueError("Invalid record ID.")

                assignments = ", ".join(
                    f"{field}=?" for field in fields
                )

                cursor = db.execute(
                    f"UPDATE {kind} SET {assignments} WHERE id=?",
                    (*cleaned, record_id),
                )

                if not cursor.rowcount:
                    raise ValueError("Record no longer exists.")

                return record_id

            placeholders = ", ".join("?" for _ in fields)

            cursor = db.execute(
                f"""
                INSERT INTO {kind} ({", ".join(fields)})
                VALUES ({placeholders})
                """,
                cleaned,
            )

            return cursor.lastrowid

    def delete_entity(self, kind, record_id):
        if kind not in ENTITY_FIELDS:
            raise ValueError("Unknown record type.")

        if isinstance(record_id, bool):
            raise ValueError("Invalid record ID.")

        try:
            record_id = int(record_id)
        except (TypeError, ValueError):
            raise ValueError("Invalid record ID.")

        if record_id <= 0:
            raise ValueError("Invalid record ID.")

        reference = {
            "drivers": "driver_id",
            "vehicles": "vehicle_id",
            "routes": "route_id",
        }[kind]

        with self.connection() as db:
            used = db.execute(
                f"""
                SELECT 1
                FROM trips
                WHERE {reference}=?
                LIMIT 1
                """,
                (record_id,),
            ).fetchone()

            if used:
                raise ValueError(
                    "This record belongs to trip history "
                    "and cannot be deleted."
                )

            cursor = db.execute(
                f"DELETE FROM {kind} WHERE id=?",
                (record_id,),
            )

            if not cursor.rowcount:
                raise ValueError("Record does not exist.")

    # ---------------------------------------------------------
    # Trip management
    # ---------------------------------------------------------

    def assign(self, vehicle_id, driver_id, route_id):
        try:
            vehicle_id = int(vehicle_id)
            driver_id = int(driver_id)
            route_id = int(route_id)
        except (TypeError, ValueError):
            raise ValueError("Invalid vehicle, driver, or route ID.")

        if min(vehicle_id, driver_id, route_id) <= 0:
            raise ValueError("Invalid vehicle, driver, or route ID.")

        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")

            vehicle = db.execute(
                "SELECT * FROM vehicles WHERE id=?",
                (vehicle_id,),
            ).fetchone()

            driver = db.execute(
                "SELECT * FROM drivers WHERE id=?",
                (driver_id,),
            ).fetchone()

            route = db.execute(
                "SELECT * FROM routes WHERE id=?",
                (route_id,),
            ).fetchone()

            if not all((vehicle, driver, route)):
                raise ValueError(
                    "Select an existing vehicle, driver, and route."
                )

            busy = db.execute(
                """
                SELECT vehicle_id
                FROM trips
                WHERE driver_id=? AND ended_at IS NULL
                """,
                (driver_id,),
            ).fetchone()

            if busy and busy["vehicle_id"] != vehicle_id:
                raise ValueError(
                    "This driver already has an active trip. "
                    "End that trip first."
                )

            now = utc_now()

            db.execute(
                """
                UPDATE trips
                SET ended_at=?
                WHERE vehicle_id=? AND ended_at IS NULL
                """,
                (now, vehicle_id),
            )

            cursor = db.execute(
                """
                INSERT INTO trips(
                    vehicle_id,
                    driver_id,
                    route_id,
                    started_at,
                    driver_name,
                    vehicle_name,
                    route_name
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    vehicle_id,
                    driver_id,
                    route_id,
                    now,
                    driver["name"],
                    vehicle["registration"],
                    route["name"],
                ),
            )

            return cursor.lastrowid

    def end_trip(self, trip_id):
        if isinstance(trip_id, bool):
            raise ValueError("Invalid trip ID.")

        try:
            trip_id = int(trip_id)
        except (TypeError, ValueError):
            raise ValueError("Invalid trip ID.")

        if trip_id <= 0:
            raise ValueError("Invalid trip ID.")

        with self.connection() as db:
            cursor = db.execute(
                """
                UPDATE trips
                SET ended_at=?
                WHERE id=? AND ended_at IS NULL
                """,
                (utc_now(), trip_id),
            )

            if not cursor.rowcount:
                raise ValueError(
                    "Trip has already ended or does not exist."
                )

    def assignment(self, vehicle_id):
        with self.connection() as db:
            row = db.execute(
                """
                SELECT *
                FROM trips
                WHERE vehicle_id=? AND ended_at IS NULL
                """,
                (vehicle_id,),
            ).fetchone()

            return dict(row) if row else None

    # ---------------------------------------------------------
    # Risk data
    # ---------------------------------------------------------

    def add_sample(self, sample):
        if not isinstance(sample, dict):
            raise ValueError("Invalid sample data.")

        required = (
            "id",
            "trip_id",
            "vehicle_id",
            "captured_at",
            "risk",
            "readings",
        )

        if any(key not in sample for key in required):
            raise ValueError("Sample is missing required fields.")

        if not isinstance(sample["id"], str) or not sample["id"].strip():
            raise ValueError("Invalid sample ID.")

        if not isinstance(sample["risk"], dict):
            raise ValueError("Invalid risk assessment.")

        if not isinstance(sample["readings"], dict):
            raise ValueError("Invalid sensor readings.")

        result = sample["risk"]

        try:
            trip_id = int(sample["trip_id"])
            vehicle_id = int(sample["vehicle_id"])
            score = int(result["score"])
            level = str(result["level"])
            reason = str(result["reason"])
            captured_at = str(sample["captured_at"])

            readings_json = json.dumps(sample["readings"])

        except (KeyError, TypeError, ValueError, OverflowError):
            raise ValueError("Invalid sample or risk assessment values.")

        if trip_id <= 0 or vehicle_id <= 0:
            raise ValueError("Invalid trip or vehicle ID.")

        if not captured_at:
            raise ValueError("Missing sample timestamp.")

        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")

            trip = db.execute(
                "SELECT * FROM trips WHERE id=?",
                (trip_id,),
            ).fetchone()

            if not trip or trip["vehicle_id"] != vehicle_id:
                raise ValueError(
                    "Sample does not belong to this vehicle's trip."
                )

            if (
                captured_at < trip["started_at"]
                or (
                    trip["ended_at"]
                    and captured_at > trip["ended_at"]
                )
            ):
                raise ValueError(
                    "Sample falls outside its trip. "
                    "Refresh the assignment."
                )

            previous = db.execute(
                """
                SELECT *
                FROM samples
                WHERE trip_id=?
                ORDER BY captured_at DESC, received_at DESC
                LIMIT 1
                """,
                (trip_id,),
            ).fetchone()

            cursor = db.execute(
                """
                INSERT OR IGNORE INTO samples(
                    id,
                    trip_id,
                    captured_at,
                    received_at,
                    score,
                    level,
                    reason,
                    readings
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    sample["id"],
                    trip_id,
                    captured_at,
                    utc_now(),
                    score,
                    level,
                    reason,
                    readings_json,
                ),
            )

            # Ignore duplicate samples.
            if not cursor.rowcount:
                return

            # Only create a risk transition event when this sample
            # is newer than the previous sample.
            is_newest = (
                previous is None
                or captured_at > previous["captured_at"]
            )

            if is_newest and (
                previous is None
                or previous["level"] != level
            ):
                db.execute(
                    """
                    INSERT INTO events(
                        sample_id,
                        trip_id,
                        captured_at,
                        level,
                        score,
                        reason
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        sample["id"],
                        trip_id,
                        captured_at,
                        level,
                        score,
                        reason,
                    ),
                )

    # ---------------------------------------------------------
    # Dashboard data
    # ---------------------------------------------------------

    def snapshot(self):
        with self.connection() as db:
            result = {
                table: [
                    dict(row)
                    for row in db.execute(
                        f"SELECT * FROM {table} ORDER BY id"
                    )
                ]
                for table in ENTITY_FIELDS
            }

            trips = [
                dict(row)
                for row in db.execute(
                    "SELECT * FROM trips ORDER BY id DESC"
                )
            ]

            result["trips"] = trips

            active = {
                trip["vehicle_id"]: trip
                for trip in trips
                if trip["ended_at"] is None
            }

            for vehicle in result["vehicles"]:
                vehicle["trip"] = active.get(vehicle["id"])
                vehicle["sample"] = None

                if vehicle["trip"]:
                    row = db.execute(
                        """
                        SELECT *
                        FROM samples
                        WHERE trip_id=?
                        ORDER BY captured_at DESC, received_at DESC
                        LIMIT 1
                        """,
                        (vehicle["trip"]["id"],),
                    ).fetchone()

                    if row:
                        vehicle["sample"] = dict(row)

                        try:
                            vehicle["sample"]["readings"] = json.loads(
                                row["readings"]
                            )
                        except (ValueError, TypeError):
                            vehicle["sample"]["readings"] = {}

            return result

    # ---------------------------------------------------------
    # Risk event logs
    # ---------------------------------------------------------

    def logs(
        self,
        vehicle_id=None,
        driver_id=None,
        level=None,
        since=None,
        until=None,
        limit=1000,
    ):
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            raise ValueError("Invalid log limit.")

        limit = max(1, min(limit, 1000))

        sql = """
            SELECT
                e.*,
                t.vehicle_name,
                t.driver_name,
                t.route_name,
                t.vehicle_id,
                t.driver_id
            FROM events e
            JOIN trips t ON t.id=e.trip_id
            WHERE 1=1
        """

        args = []

        for field, value in (
            ("t.vehicle_id", vehicle_id),
            ("t.driver_id", driver_id),
            ("e.level", level),
        ):
            if value not in (None, "", "ALL"):
                if field in ("t.vehicle_id", "t.driver_id"):
                    try:
                        value = int(value)
                    except (TypeError, ValueError):
                        raise ValueError("Invalid log filter ID.")

                sql += f" AND {field}=?"
                args.append(value)

        if since:
            sql += " AND e.captured_at>=?"
            args.append(since)

        if until:
            sql += " AND e.captured_at<=?"
            args.append(until)

        sql += """
            ORDER BY e.captured_at DESC, e.id DESC
            LIMIT ?
        """

        args.append(limit)

        with self.connection() as db:
            return [
                dict(row)
                for row in db.execute(sql, args)
            ]
