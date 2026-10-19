"""Tests for OS4-2 event vs receipt time. Run: PYTHONPATH=src python -m unittest discover -s tests -v"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "src"))

from edge.teams.os4_iot import s2_event_vs_receipt_time as m   # noqa: E402


class TestS2EventVsReceiptTime(unittest.TestCase):
    def test_late_event_corrects_a_closed_window(self):
        w = m.EventTimeWindower(allowed_lateness=0.5)
        w.add(m.BASE + 0.1, 10.0)
        w.add(m.BASE + 2.0, 99.0)                 # watermark passes window 0 -> it is emitted as 10.0
        self.assertEqual(w.first_emit[0], 10.0)
        w.add(m.BASE + 0.5, 20.0)                 # late reading for the closed window 0
        self.assertEqual(w.late, 1)
        self.assertEqual(w.finish()[0], 15.0)     # corrected final value

    def test_window_assignment(self):
        self.assertEqual(m.window_of(m.BASE + 0.999), 0)
        self.assertEqual(m.window_of(m.BASE + 1.0), 1)

    def test_scenario_passes(self):
        ok, lines = m.run()
        self.assertTrue(ok, "\n".join(lines))


if __name__ == "__main__":
    unittest.main()
