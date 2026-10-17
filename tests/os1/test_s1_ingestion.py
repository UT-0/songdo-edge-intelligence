"""Tests for OS1-1 sensor ingestion and cached GeoJSON context."""
import json
import os
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
import sys
sys.path.insert(0, str(ROOT / "src"))
from edge.teams.os1_building import s1_ingestion as m  # noqa: E402


class TestS1Ingestion(unittest.TestCase):
    def test_sensor_events_are_stored_with_outbox(self):
        with tempfile.TemporaryDirectory() as tmp:
            ok, lines = m.run(ticks=7, db_path=os.path.join(tmp, "test.db"),
                              inventory_path=os.path.join(tmp, "missing.geojson"))
            self.assertTrue(ok, "\n".join(lines))
            self.assertIn("events persisted: 14", "\n".join(lines))

    def test_cached_geojson_is_loaded_and_room_can_be_matched(self):
        doc = {"type": "FeatureCollection", "features": [
            {"type": "Feature", "id": "B-12", "properties": {"room_id": "R-12"},
             "geometry": {"type": "Point", "coordinates": [126.6, 37.3]}}
        ]}
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "cache.geojson")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(doc, f)
            features = m.load_cached_inventory(path)
            self.assertEqual(len(features), 1)
            self.assertEqual(m.match_building("R-12", features)["id"], "B-12")

    def test_invalid_geojson_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "bad.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"type": "Feature", "features": []}, f)
            with self.assertRaises(ValueError):
                m.load_cached_inventory(path)


if __name__ == "__main__":
    unittest.main()
