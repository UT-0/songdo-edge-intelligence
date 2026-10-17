"""Tests for OS2-2 jitter measurement. Run: PYTHONPATH=src python -m unittest discover -s tests -v"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "src"))

from edge.teams.os2_robot import s2_jitter as m   # noqa: E402


class TestS2Jitter(unittest.TestCase):
    def test_jitter_formula_J_equals_abs_dt_minus_T(self):
        T = 0.05
        stamps = [0.0, 0.050, 0.108, 0.150]       # intervals 50, 58, 42 ms -> jitter 0, 8, 8 ms
        s = m.stats(stamps, period=T)
        self.assertEqual(s["ticks"], 3)
        self.assertAlmostEqual(s["mean_ms"], 16 / 3, places=6)
        self.assertAlmostEqual(s["max_ms"], 8.0, places=6)
        self.assertAlmostEqual(s["drift_ms"], 0.0, places=6)   # 150 ms for 3 ticks of 50 ms

    def test_scenario_passes(self):
        ok, lines = m.run()
        self.assertTrue(ok, "\n".join(lines))


if __name__ == "__main__":
    unittest.main()
