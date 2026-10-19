"""Tests for OS4-5 backlog drain. Run: PYTHONPATH=src python -m unittest discover -s tests -v"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "src"))

import tempfile   # noqa: E402

from edge.teams.os4_iot import s5_backlog_drain as m   # noqa: E402


class TestS5BacklogDrain(unittest.TestCase):
    def test_missing_baseline_is_labelled_simulated(self):
        vals, label = m.load_baseline("/nonexistent/file.csv")
        self.assertEqual(len(vals), m.HOURS)
        self.assertIn("SIMULATED", label)

    def test_cached_baseline_file_is_used_and_header_skipped(self):
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as f:
            f.write("hour,pm25\n" + "".join(f"{h},{20 + h}\n" for h in range(8)))
        vals, label = m.load_baseline(f.name)
        os.unlink(f.name)
        self.assertEqual(vals, [20.0, 21.0, 22.0, 23.0, 24.0, 25.0])
        self.assertNotIn("SIMULATED", label)

    def test_scenario_passes(self):
        ok, lines = m.run()
        self.assertTrue(ok, "\n".join(lines))


if __name__ == "__main__":
    unittest.main()
