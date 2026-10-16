"""Tests for OS3-2 alarms overtake logs. Run: PYTHONPATH=src python -m unittest discover -s tests -v"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "src"))

from edge.teams.os3_mobility import s2_priority_queue as m   # noqa: E402


class TestS2PriorityQueue(unittest.TestCase):
    def test_scenario_passes(self):
        ok, lines = m.run()
        self.assertTrue(ok, "\n".join(lines))

    def test_high_served_first_and_never_dropped_for_low(self):
        q = m.PriorityBoundedQueue(maxsize=5)
        for i in range(5):
            q.put(("log", i), q.LOW)
        q.put(("ALARM", 1), q.HIGH)
        self.assertEqual(q.get(0.1), ("ALARM", 1))
        self.assertEqual(q.get(0.1), ("log", 1))      # log 0 was the victim
        self.assertEqual(q.dropped[q.LOW], 1)
        self.assertEqual(q.dropped[q.HIGH], 0)


if __name__ == "__main__":
    unittest.main()
