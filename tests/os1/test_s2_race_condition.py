"""Tests for OS1-2 competing occupancy writers and Mutex protection."""
import os
import sys
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from edge.teams.os1_building import s2_race_condition as m  # noqa: E402


class TestS2RaceCondition(unittest.TestCase):
    def test_unsafe_counter_loses_updates_and_mutex_preserves_them(self):
        ok, lines = m.run(workers=80)
        self.assertTrue(ok, "\n".join(lines))
        report = "\n".join(lines)
        self.assertIn("without Mutex: 1", report)
        self.assertIn("with Mutex: 80", report)

    def test_requires_competing_writers(self):
        with self.assertRaises(ValueError):
            m.run(workers=1)


if __name__ == "__main__":
    unittest.main()
