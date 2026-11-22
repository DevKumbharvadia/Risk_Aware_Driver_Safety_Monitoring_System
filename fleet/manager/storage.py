"""SQLite persistence. Each operation owns its connection (safe across threads)."""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3


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
                    id INTEGER PRIMARY KEY, name TEXT NOT NULL, license TEXT NOT NULL UNIQUE,
                    phone TEXT NOT NULL DEFAULT '');
                CREATE TABLE IF NOT EXISTS vehicles (
                    id INTEGER PRIMARY KEY, registration TEXT NOT NULL UNIQUE, model TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS routes (
                    id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE,
                    origin TEXT NOT NULL, destination TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS trips (
                    id INTEGER PRIMARY KEY, vehicle_id INTEGER NOT NULL REFERENCES vehicles(id),
                    driver_id INTEGER NOT NULL REFERENCES drivers(id), route_id INTEGER NOT NULL REFERENCES routes(id),
                    started_at TEXT NOT NULL, ended_at TEXT,
                    driver_name TEXT NOT NULL, vehicle_name TEXT NOT NULL, route_name TEXT NOT NULL);
                CREATE UNIQUE INDEX IF NOT EXISTS active_vehicle ON trips(vehicle_id) WHERE ended_at IS NULL;
                CREATE UNIQUE INDEX IF NOT EXISTS active_driver ON trips(driver_id) WHERE ended_at IS NULL;
                CREATE TABLE IF NOT EXISTS samples (
                    id TEXT PRIMARY KEY, trip_id INTEGER NOT NULL REFERENCES trips(id),
                    captured_at TEXT NOT NULL, received_at TEXT NOT NULL,
                    score INTEGER NOT NULL, level TEXT NOT NULL, reason TEXT NOT NULL,
                    readings TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS sample_trip_time ON samples(trip_id, captured_at);
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY, sample_id TEXT UNIQUE REFERENCES samples(id),
                    trip_id INTEGER NOT NULL REFERENCES trips(id), captured_at TEXT NOT NULL,
                    level TEXT NOT NULL, score INTEGER NOT NULL, reason TEXT NOT NULL);
            """)

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def seed(self):
        with self.connection() as db:
            if any(db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in ("vehicles", "drivers", "routes")):
                return
            for index, name in enumerate(("Aarav Shah", "Meera Patel", "Kabir Desai"), 1):
                db.execute("INSERT INTO drivers(name, license, phone) VALUES(?,?,?)", (name, f"LIC-{index:03}", "Contact"))
                db.execute("INSERT INTO vehicles(registration, model) VALUES(?,?)", (f"VEH-{index:03}", "Lab vehicle"))
                db.execute("INSERT INTO routes(name, origin, destination) VALUES(?,?,?)", (f"Route {index}", "Depot", ("Campus", "Station", "Warehouse")[index-1]))
                db.execute("INSERT INTO trips(vehicle_id, driver_id, route_id, started_at, driver_name, vehicle_name, route_name) VALUES(?,?,?,?,?,?,?)",
                           (index, index, index, utc_now(), name, f"VEH-{index:03}", f"Route {index}"))

    def save_entity(self, kind, values):
        columns = {"drivers": ("name", "license", "phone"), "vehicles": ("registration", "model"),
                   "routes": ("name", "origin", "destination")}
        if kind not in columns:
            raise ValueError("Unknown record type.")
        fields = columns[kind]
        cleaned = []
        for field in fields:
            value = values.get(field, "")
            if not isinstance(value, str) or len(value.strip()) > 100 or (not value.strip() and field != "phone"):
                raise ValueError(f"Enter a valid {field} (up to 100 characters).")
            cleaned.append(value.strip())
        with self.connection() as db:
            if values.get("id"):
                cursor = db.execute(f"UPDATE {kind} SET " + ",".join(f"{field}=?" for field in fields) + " WHERE id=?", (*cleaned, int(values["id"])))
                if not cursor.rowcount:
                    raise ValueError("Record no longer exists.")
                return int(values["id"])
            cursor = db.execute(f"INSERT INTO {kind} ({','.join(fields)}) VALUES ({','.join('?' for _ in fields)})", cleaned)
            return cursor.lastrowid

    def assign(self, vehicle_id, driver_id, route_id):
        with self.connection() as db:
            # Serialize assignment changes so ending and replacing a trip is atomic.
            db.execute("BEGIN IMMEDIATE")
            vehicle = db.execute("SELECT * FROM vehicles WHERE id=?", (vehicle_id,)).fetchone()
            driver = db.execute("SELECT * FROM drivers WHERE id=?", (driver_id,)).fetchone()
            route = db.execute("SELECT * FROM routes WHERE id=?", (route_id,)).fetchone()
            if not all((vehicle, driver, route)):
                raise ValueError("Select an existing vehicle, driver, and route.")
            busy = db.execute("SELECT vehicle_id FROM trips WHERE driver_id=? AND ended_at IS NULL", (driver_id,)).fetchone()
            if busy and busy[0] != vehicle_id:
                raise ValueError("This driver already has an active trip. End that trip first.")
            now = utc_now()
            db.execute("UPDATE trips SET ended_at=? WHERE vehicle_id=? AND ended_at IS NULL", (now, vehicle_id))
            cursor = db.execute("INSERT INTO trips(vehicle_id, driver_id, route_id, started_at, driver_name, vehicle_name, route_name) VALUES(?,?,?,?,?,?,?)",
                                (vehicle_id, driver_id, route_id, now, driver["name"], vehicle["registration"], route["name"]))
            return cursor.lastrowid

    def end_trip(self, trip_id):
        with self.connection() as db:
            cursor = db.execute("UPDATE trips SET ended_at=? WHERE id=? AND ended_at IS NULL", (utc_now(), trip_id))
            if not cursor.rowcount:
                raise ValueError("Trip has already ended or does not exist.")

    def assignment(self, vehicle_id):
        with self.connection() as db:
            row = db.execute("SELECT * FROM trips WHERE vehicle_id=? AND ended_at IS NULL", (vehicle_id,)).fetchone()
            return dict(row) if row else None

    def add_sample(self, sample):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            trip = db.execute("SELECT * FROM trips WHERE id=?", (sample["trip_id"],)).fetchone()
            if not trip or trip["vehicle_id"] != sample["vehicle_id"]:
                raise ValueError("Sample does not belong to this vehicle's trip.")
            if sample["captured_at"] < trip["started_at"] or (trip["ended_at"] and sample["captured_at"] > trip["ended_at"]):
                raise ValueError("Sample falls outside its trip. Refresh the assignment.")
            result = sample["risk"]
            previous = db.execute("SELECT * FROM samples WHERE trip_id=? ORDER BY captured_at DESC LIMIT 1", (sample["trip_id"],)).fetchone()
            cursor = db.execute("INSERT OR IGNORE INTO samples(id,trip_id,captured_at,received_at,score,level,reason,readings) VALUES(?,?,?,?,?,?,?,?)", (
                sample["id"], sample["trip_id"], sample["captured_at"], utc_now(), result["score"], result["level"],
                result["reason"], json.dumps(sample["readings"])))
            if cursor.rowcount and (previous is None or previous["level"] != result["level"]):
                db.execute("INSERT INTO events(sample_id,trip_id,captured_at,level,score,reason) VALUES(?,?,?,?,?,?)", (
                    sample["id"], sample["trip_id"], sample["captured_at"], result["level"], result["score"], result["reason"]))

    def snapshot(self):
        with self.connection() as db:
            result = {table: [dict(row) for row in db.execute(f"SELECT * FROM {table} ORDER BY id")] for table in ("drivers", "vehicles", "routes")}
            trips = [dict(row) for row in db.execute("SELECT * FROM trips ORDER BY id DESC")]
            result["trips"] = trips
            active = {trip["vehicle_id"]: trip for trip in trips if trip["ended_at"] is None}
            for vehicle in result["vehicles"]:
                vehicle["trip"] = active.get(vehicle["id"])
                vehicle["sample"] = None
                if vehicle["trip"]:
                    row = db.execute("SELECT * FROM samples WHERE trip_id=? ORDER BY captured_at DESC LIMIT 1", (vehicle["trip"]["id"],)).fetchone()
                    if row:
                        vehicle["sample"] = dict(row)
                        vehicle["sample"]["readings"] = json.loads(row["readings"])
            return result

    def logs(self, vehicle_id=None, driver_id=None, level=None, since=None, until=None, limit=1000):
        sql = "SELECT e.*, t.vehicle_name, t.driver_name, t.route_name, t.vehicle_id, t.driver_id FROM events e JOIN trips t ON t.id=e.trip_id WHERE 1=1"
        args = []
        for field, value in (("t.vehicle_id", vehicle_id), ("t.driver_id", driver_id), ("e.level", level)):
            if value not in (None, "", "ALL"):
                sql += f" AND {field}=?"
                args.append(value)
        if since:
            sql += " AND e.captured_at>=?"
            args.append(since)
        if until:
            sql += " AND e.captured_at<=?"
            args.append(until)
        sql += " ORDER BY e.captured_at DESC LIMIT ?"
        args.append(limit)
        with self.connection() as db:
            return [dict(row) for row in db.execute(sql, args)]
