
"""SQLite persistence. Each operation owns its connection."""

from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import math


ENTITY_FIELDS = {
    "drivers": ("name", "license", "phone"),
    "vehicles": ("registration", "model"),
    "routes": ("name", "origin", "destination"),
}

ENTITY_LABELS = {
    "drivers": "driver",
    "vehicles": "vehicle",
    "routes": "route",
}


def utc_now():
    """Return the current UTC time as an ISO timestamp."""

    return datetime.now(timezone.utc).isoformat(
        timespec="milliseconds"
    )


def parse_timestamp(value, label="timestamp"):
    """Parse an ISO timestamp and return an aware UTC datetime."""

    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Invalid {label}.")

    value = value.strip()

    if value.endswith("Z"):
        value = value[:-1] + "+00:00"

    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError, OverflowError):
        raise ValueError(f"Invalid {label}.") from None

    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label.title()} must include a timezone.")

    return parsed.astimezone(timezone.utc)


def normalize_timestamp(value, label="timestamp"):
    """Validate and normalize an ISO timestamp to UTC."""

    return parse_timestamp(value, label).isoformat(
        timespec="milliseconds"
    )


def positive_id(value, label="record"):
    """Convert a value into a valid positive database ID."""

    if isinstance(value, bool):
        raise ValueError(f"Invalid {label} ID.")

    try:
        result = int(value)
    except (TypeError, ValueError, OverflowError):
        raise ValueError(f"Invalid {label} ID.") from None

    if isinstance(value, float):
        if not math.isfinite(value) or not value.is_integer():
            raise ValueError(f"Invalid {label} ID.")

    if isinstance(value, str) and str(result) != value.strip():
        raise ValueError(f"Invalid {label} ID.")

    if result <= 0:
        raise ValueError(f"Invalid {label} ID.")

    return result


def non_negative_integer(value, label):
    """Validate an integer-valued, non-negative numeric value."""

    if isinstance(value, bool):
        raise ValueError(f"Invalid {label}.")

    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        raise ValueError(f"Invalid {label}.") from None

    if (
        not math.isfinite(number)
        or number < 0
        or not number.is_integer()
    ):
        raise ValueError(f"Invalid {label}.")

    return int(number)


class Store:
    """Thread-safe SQLite storage for fleet and risk data."""

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
        """Create and safely close an independent SQLite connection."""

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

    # Initial data

    def seed(self):
        """Insert demonstration records into an empty database."""

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

        with self.connection() as db:

            counts = [
                db.execute(
                    f"SELECT COUNT(*) FROM {table}"
                ).fetchone()[0]
                for table in (
                    "vehicles",
                    "drivers",
                    "routes",
                )
            ]

            if any(counts):
                return

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
                    (
                        name,
                        license_number,
                        phone,
                    ),
                )

                db.execute(
                    """
                    INSERT INTO vehicles(registration, model)
                    VALUES (?, ?)
                    """,
                    (
                        vehicle,
                        "Lab vehicle",
                    ),
                )

                db.execute(
                    """
                    INSERT INTO routes(name, origin, destination)
                    VALUES (?, ?, ?)
                    """,
                    (
                        route,
                        "Depot",
                        destinations[index - 1],
                    ),
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

    # Entity management

    def save_entity(self, kind, values):
        """Create or update a driver, vehicle, or route."""

        if kind not in ENTITY_FIELDS:
            raise ValueError("Unknown record type.")

        if not isinstance(values, dict):
            raise ValueError("Invalid record data.")

        fields = ENTITY_FIELDS[kind]
        cleaned = []

        for field in fields:

            value = values.get(field, "")

            if not isinstance(value, str):
                raise ValueError(f"Enter a valid {field}.")

            value = value.strip()

            if len(value) > 100:
                raise ValueError(
                    f"{field.title()} must not exceed 100 characters."
                )

            if not value and field != "phone":
                label = field.replace("_", " ").title()
                raise ValueError(f"{label} is required.")

            cleaned.append(value)

        record_id = values.get("id")

        with self.connection() as db:

            if record_id is not None:

                record_id = positive_id(
                    record_id,
                    ENTITY_LABELS[kind],
                )

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

            placeholders = ", ".join(
                "?" for _ in fields
            )

            cursor = db.execute(
                f"""
                INSERT INTO {kind} ({", ".join(fields)})
                VALUES ({placeholders})
                """,
                cleaned,
            )

            return cursor.lastrowid

    def delete_entity(self, kind, record_id):
        """Delete an entity only when it has no trip history."""

        if kind not in ENTITY_FIELDS:
            raise ValueError("Unknown record type.")

        record_id = positive_id(
            record_id,
            ENTITY_LABELS[kind],
        )

        reference = {
            "drivers": "driver_id",
            "vehicles": "vehicle_id",
            "routes": "route_id",
        }[kind]

        with self.connection() as db:

            used = db.execute(
                f"""
                SELECT 1 FROM trips
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

    # Trip management

    def assign(self, vehicle_id, driver_id, route_id):
        """End the vehicle's previous trip and create a new assignment."""

        vehicle_id = positive_id(vehicle_id, "vehicle")
        driver_id = positive_id(driver_id, "driver")
        route_id = positive_id(route_id, "route")

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
                SELECT vehicle_id FROM trips
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
                UPDATE trips SET ended_at=?
                WHERE vehicle_id=? AND ended_at IS NULL
                """,
                (
                    now,
                    vehicle_id,
                ),
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
        """End an active trip."""

        trip_id = positive_id(
            trip_id,
            "trip",
        )

        with self.connection() as db:

            cursor = db.execute(
                """
                UPDATE trips SET ended_at=?
                WHERE id=? AND ended_at IS NULL
                """,
                (
                    utc_now(),
                    trip_id,
                ),
            )

            if not cursor.rowcount:
                raise ValueError(
                    "Trip has already ended or does not exist."
                )

    def assignment(self, vehicle_id):
        """Return a vehicle's active trip."""

        vehicle_id = positive_id(
            vehicle_id,
            "vehicle",
        )

        with self.connection() as db:

            row = db.execute(
                """
                SELECT * FROM trips
                WHERE vehicle_id=? AND ended_at IS NULL
                """,
                (vehicle_id,),
            ).fetchone()

            return dict(row) if row else None

    # Risk data

    def add_sample(self, sample):
        """Store a risk sample and create a transition event when needed."""

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

        sample_id = sample["id"]

        if (
            not isinstance(sample_id, str)
            or not sample_id.strip()
            or len(sample_id) > 128
        ):
            raise ValueError("Invalid sample ID.")

        risk = sample["risk"]
        readings = sample["readings"]

        if not isinstance(risk, dict):
            raise ValueError("Invalid risk assessment.")

        if not isinstance(readings, dict):
            raise ValueError("Invalid sensor readings.")

        try:
            trip_id = positive_id(
                sample["trip_id"],
                "trip",
            )

            vehicle_id = positive_id(
                sample["vehicle_id"],
                "vehicle",
            )

            score = non_negative_integer(
                risk["score"],
                "risk score",
            )

            level = risk["level"]
            reason = risk["reason"]

            captured_datetime = parse_timestamp(
                sample["captured_at"],
                "sample timestamp",
            )

            captured_at = captured_datetime.isoformat(
                timespec="milliseconds"
            )

            if not isinstance(level, str) or not level.strip():
                raise ValueError("Invalid risk level.")

            if not isinstance(reason, str):
                raise ValueError("Invalid risk reason.")

            readings_json = json.dumps(
                readings,
                allow_nan=False,
            )

        except (
            KeyError,
            TypeError,
            ValueError,
            OverflowError,
        ) as error:

            raise ValueError(
                "Invalid sample or risk assessment values."
            ) from error

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

            trip_started = parse_timestamp(
                trip["started_at"],
                "trip start timestamp",
            )

            if captured_datetime < trip_started:
                raise ValueError(
                    "Sample falls outside its trip. "
                    "Refresh the assignment."
                )

            if trip["ended_at"]:

                trip_ended = parse_timestamp(
                    trip["ended_at"],
                    "trip end timestamp",
                )

                if captured_datetime > trip_ended:
                    raise ValueError(
                        "Sample falls outside its trip. "
                        "Refresh the assignment."
                    )

            previous = db.execute(
                """
                SELECT * FROM samples
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
                    sample_id,
                    trip_id,
                    captured_at,
                    utc_now(),
                    score,
                    level,
                    reason,
                    readings_json,
                ),
            )

            if not cursor.rowcount:
                return

            if previous is None:
                is_newest = True
                changed_level = True

            else:
                previous_datetime = parse_timestamp(
                    previous["captured_at"],
                    "previous sample timestamp",
                )

                is_newest = (
                    captured_datetime > previous_datetime
                )

                changed_level = (
                    previous["level"] != level
                )

            if is_newest and changed_level:

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
                        sample_id,
                        trip_id,
                        captured_at,
                        level,
                        score,
                        reason,
                    ),
                )

    # Dashboard data

    def snapshot(self):
        """Return entities, trips, and each active vehicle's latest sample."""

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

                trip = active.get(vehicle["id"])

                vehicle["trip"] = trip
                vehicle["sample"] = None

                if not trip:
                    continue

                row = db.execute(
                    """
                    SELECT * FROM samples
                    WHERE trip_id=?
                    ORDER BY captured_at DESC, received_at DESC
                    LIMIT 1
                    """,
                    (trip["id"],),
                ).fetchone()

                if row:

                    sample = dict(row)

                    try:
                        sample["readings"] = json.loads(
                            row["readings"]
                        )

                    except (
                        ValueError,
                        TypeError,
                    ):
                        sample["readings"] = {}

                    vehicle["sample"] = sample

            return result

    # Risk event logs

    def logs(
        self,
        vehicle_id=None,
        driver_id=None,
        level=None,
        since=None,
        until=None,
        limit=1000,
    ):
        """Return filtered risk transition events."""

        try:
            limit = positive_id(
                limit,
                "log limit",
            )

        except ValueError:
            raise ValueError("Invalid log limit.") from None

        limit = min(limit, 1000)

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

        filters = (
            ("t.vehicle_id", vehicle_id, "vehicle"),
            ("t.driver_id", driver_id, "driver"),
            ("e.level", level, None),
        )

        for field, value, label in filters:

            if value in (None, "", "ALL"):
                continue

            if label:
                value = positive_id(
                    value,
                    label,
                )

            sql += f" AND {field}=?"
            args.append(value)

        if since:
            since = normalize_timestamp(
                since,
                "start date",
            )

            sql += " AND e.captured_at>=?"
            args.append(since)

        if until:
            until = normalize_timestamp(
                until,
                "end date",
            )

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
                for row in db.execute(
                    sql,
                    args,
                )
            ]
