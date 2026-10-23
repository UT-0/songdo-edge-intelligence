"""Portable checks for the Linux verifier's failure and artifact contracts."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

SPEC = importlib.util.spec_from_file_location("verify_linux", Path(__file__).resolve().parents[1] / "scripts/verify_linux.py")
verify = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verify)


class VerificationTests(unittest.TestCase):
    def test_windows_rejected_before_tests_or_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "result"
            with patch.object(verify.sys, "platform", "win32"), patch.object(verify, "run_stage") as stage:
                with contextlib.redirect_stderr(io.StringIO()) as message:
                    self.assertEqual(verify.main(["--output", str(output)]), 2)
                self.assertIn("Linux", message.getvalue())
                stage.assert_not_called()
                self.assertFalse(output.exists())

    def test_empty_skipped_and_failed_suites_are_not_success(self):
        self.assertFalse(verify.tests_passed({"tests_run": 0}))
        self.assertFalse(verify.tests_passed({"tests_run": 3, "skipped": 1}))
        self.assertFalse(verify.tests_passed({"tests_run": 3, "errors": 1}))
        self.assertTrue(verify.tests_passed({"tests_run": 3}))

    def test_timeout_and_interrupt_kill_whole_process_group(self):
        for error, status in ((subprocess.TimeoutExpired("child", 1), "timeout"),
                              (KeyboardInterrupt(), "interrupted")):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as directory:
                process = Mock(pid=123)
                process.wait.side_effect = [error, 0]
                with patch.object(verify.subprocess, "Popen", return_value=process) as popen:
                    with patch.object(verify.os, "killpg", create=True) as kill, patch.object(verify.signal, "SIGKILL", 9, create=True):
                        result = verify.run_stage(["child"], Path(directory) / "stage.log", 1, {})
                self.assertEqual(result["status"], status)
                self.assertEqual(kill.call_args.args[0], 123)
                self.assertTrue(popen.call_args.kwargs["start_new_session"])
                self.assertEqual(popen.call_args.kwargs["stderr"], subprocess.STDOUT)

    def test_launch_error_is_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(verify.subprocess, "Popen", side_effect=OSError("launch failed")):
                result = verify.run_stage(["child"], Path(directory) / "stage.log", 1, {})
        self.assertEqual(result["status"], "failed")
        self.assertIn("launch failed", result["error"])

    def test_failed_tests_still_run_scenarios_and_write_summary(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "result"
            with patch.object(verify, "unsupported_reason", return_value=None), patch.object(verify, "metadata", return_value={}):
                with patch.object(verify, "scenario_modules", return_value=[str(i) for i in range(25)]):
                    with patch.object(verify, "run_stage", side_effect=[{"status": "failed"}, {"status": "passed"}]) as stage:
                        self.assertEqual(verify.main(["--output", str(output)]), 1)
            result = json.loads((output / "summary.json").read_text())
            self.assertEqual(result["status"], "failed")
            self.assertEqual(stage.call_count, 2)

    def test_interruption_writes_summary_and_does_not_start_next_stage(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "result"
            with patch.object(verify, "unsupported_reason", return_value=None), patch.object(verify, "metadata", return_value={}):
                with patch.object(verify, "run_stage", return_value={"status": "interrupted"}) as stage:
                    self.assertEqual(verify.main(["--output", str(output)]), 1)
            result = json.loads((output / "summary.json").read_text())
            self.assertEqual(result["stages"]["scenarios"]["status"], "not_run")
            self.assertEqual(stage.call_count, 1)

    def test_existing_output_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(verify, "unsupported_reason", return_value=None), patch.object(verify, "run_stage") as stage:
                with contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(verify.main(["--output", directory]), 2)
                stage.assert_not_called()


if __name__ == "__main__":
    unittest.main()
