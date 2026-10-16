"""Tests for OS3-1 real bus context + stored stream. Run: PYTHONPATH=src python -m unittest discover -s tests -v"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "src"))

from edge.teams.os3_mobility import s1_bus_stop_context as m   # noqa: E402


class TestS1BusStopContext(unittest.TestCase):
    def test_scenario_passes(self):
        ok, lines = m.run()
        self.assertTrue(ok, "\n".join(lines))

    def test_context_is_real_data(self):
        doc = m.load_bus_context()
        self.assertIs(doc["sample"], False)
        self.assertGreater(len(doc["stops"]), 0)
        self.assertTrue(all(r["route_id"] for s in doc["stops"] for r in s["routes"]))


if __name__ == "__main__":
    unittest.main()
