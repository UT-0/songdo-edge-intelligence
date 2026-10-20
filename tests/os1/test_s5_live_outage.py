"""Tests for the real-time WAN outage run in OS1-5."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from edge.teams.os1_building import s5_wan_outage as m  # noqa: E402


class TestS5LiveOutage(unittest.TestCase):
    def test_live_outage_keeps_actuating_and_loses_nothing(self):
        ok, lines = m.run_live(online_s=1.0, outage_s=3.0, restored_s=1.0)
        self.assertTrue(ok, "\n".join(lines))


if __name__ == "__main__":
    unittest.main()
