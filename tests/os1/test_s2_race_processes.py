"""Tests for the real-process race in OS1-2."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from edge.teams.os1_building import s2_race_condition as m  # noqa: E402


class TestS2RaceProcesses(unittest.TestCase):
    def test_processes_lose_updates_without_lock_and_none_with_it(self):
        expected, res = m.run_processes()
        self.assertEqual(expected, 80)
        self.assertLess(res["unprotected"], 80)
        self.assertEqual(res["locked"], 80)

    def test_full_scenario_includes_both_demos(self):
        ok, lines = m.run()
        self.assertTrue(ok, "\n".join(lines))
        self.assertTrue(any("real processes" in line for line in lines))


if __name__ == "__main__":
    unittest.main()
