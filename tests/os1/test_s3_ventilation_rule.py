"""Tests for OS1-3 CO2 rule and monotonic command expiry."""
import os
import sys
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from edge.teams.os1_building import s3_ventilation_rule as m  # noqa: E402


class TestS3VentilationRule(unittest.TestCase):
    def test_rule_triggers_only_above_1000_ppm(self):
        self.assertIsNone(m.evaluate_co2(1000, "event-1", now_mono=10.0))
        decision = m.evaluate_co2(1001, "event-2", now_mono=10.0)
        self.assertIsNotNone(decision)
        self.assertEqual(decision.actuator, "HVAC_DAMPER_PCT")
        self.assertEqual(decision.command_value, 100.0)
        self.assertEqual(decision.expires_mono, 25.0)

    def test_expired_command_is_not_dispatched(self):
        decision = m.evaluate_co2(1200, "event-3", now_mono=10.0)
        self.assertEqual(m.dispatch_if_fresh(decision, now_mono=24.99), "DISPATCHED")
        self.assertEqual(m.dispatch_if_fresh(decision, now_mono=25.0), "EXPIRED")

    def test_scenario_persists_and_dispatches_decision(self):
        ok, lines = m.run(co2_ppm=1200, now_mono=10.0)
        self.assertTrue(ok, "\n".join(lines))


if __name__ == "__main__":
    unittest.main()
