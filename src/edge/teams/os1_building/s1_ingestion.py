"""OS1-1: Local Room Sensor Ingestion & Cached Inventory.

Reads indoor CO2/temperature readings, optionally loads a cached VWorld GeoJSON
inventory, and persists each reading using the shared atomic event+outbox API.
The project archive does not include the VWorld cache itself; put it at
 data/vworld_buildings.geojson (or pass inventory_path explicitly).
"""
import json
import os
import random
import sys
import tempfile
import time
from pathlib import Path

from edge.core.models import SensorEvent
from edge.core.storage import Storage

ROOT = Path(__file__).resolve().parents[4]
SCHEMA = ROOT / "sql" / "schema.sql"
DEFAULT_INVENTORY = ROOT / "data" / "vworld_buildings.geojson"
NODE_ID = "EDGE_NODE_OS1_CONVENSIA"


def load_cached_inventory(path=DEFAULT_INVENTORY):
    """Load a cached GeoJSON FeatureCollection; never makes a network request.

    Returns a list of features. A missing cache returns an empty list so local
    sensor ingestion can still operate while reporting that context is absent.
    Invalid JSON/GeoJSON raises ValueError instead of silently hiding corruption.
    """
    path = Path(path)
    if not path.exists():
        return []
    try:
        with path.open(encoding="utf-8") as f:
            doc = json.load(f)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid cached GeoJSON: {path}") from exc
    if doc.get("type") != "FeatureCollection" or not isinstance(doc.get("features"), list):
        raise ValueError("Cached inventory must be a GeoJSON FeatureCollection")
    return doc["features"]


def match_building(room_id, features):
    """Match a room identifier to a feature's common ID properties, if present."""
    target = str(room_id)
    for feature in features:
        props = feature.get("properties") or {}
        identifiers = (props.get("room_id"), props.get("building_id"), props.get("id"),
                       feature.get("id"))
        if target in {str(x) for x in identifiers if x is not None}:
            return feature
    return None


def run(ticks=20, seed=7, db_path=None, inventory_path=DEFAULT_INVENTORY):
    """Run a deterministic sensor-ingestion demonstration; return (ok, lines)."""
    if ticks < 1:
        raise ValueError("ticks must be at least 1")
    features = load_cached_inventory(inventory_path)
    rng = random.Random(seed)
    base = time.time()
    temp_dir = tempfile.TemporaryDirectory() if db_path is None else None
    try:
        path = db_path or os.path.join(temp_dir.name, "os1_s1.db")
        db = Storage(path, str(SCHEMA))
        stored_ok = 0
        for tick in range(ticks):
            co2 = max(350.0, rng.gauss(650.0, 55.0))
            temperature = rng.gauss(22.0, 1.2)
            for sensor, value, unit in (("INDOOR_CO2_PPM", co2, "ppm"),
                                        ("ROOM_TEMPERATURE_C", temperature, "C")):
                event = SensorEvent(NODE_ID, sensor, round(value, 2), unit,
                                    observed_at=base + tick, received_at=time.time())
                stored_ok += int(db.insert_event_with_outbox(event))
        counts = db.counts()
        pending = db.outbox_pending()
        ok = stored_ok == 2 * ticks and counts["events"] == 2 * ticks and pending == 2 * ticks
        context = (f"cached inventory loaded: {len(features)} GeoJSON building feature(s)"
                   if features else "cached VWorld inventory missing/empty; sensor ingestion continued offline")
        return ok, [
            context,
            f"sensor readings generated: {2 * ticks} (CO2 ppm + room temperature C)",
            f"events persisted: {counts['events']}; outbox pending: {pending}",
            "event and outbox rows are written atomically by shared Storage",
        ]
    finally:
        if temp_dir is not None:
            temp_dir.cleanup()


def main():
    ok, lines = run()
    print(f"[{'PASS' if ok else 'FAIL'}] OS1-1 Local room sensor ingestion & cached inventory")
    for line in lines:
        print("      ", line)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
