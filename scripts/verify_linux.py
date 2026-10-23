#!/usr/bin/env python3
"""Reproducible Linux validation; artifacts are retained for every accepted run."""
import argparse
import datetime
import importlib.metadata
import json
import math
import os
from pathlib import Path
import platform
import signal
import sqlite3
import subprocess
import sys
import time
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]


def unsupported_reason():
    if sys.platform != "linux" or not Path("/proc/self/stat").is_file():
        return "Run this verifier on Linux with /proc mounted (Ubuntu or WSL2); Windows is unsupported."
    if sys.version_info < (3, 12):
        return "Run this verifier with Python 3.12 or newer on Linux."
    return None


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def test_child(result_path):
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), top_level_dir=str(ROOT))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    counts = dict(tests_run=result.testsRun, failures=len(result.failures),
                  errors=len(result.errors), skipped=len(result.skipped),
                  expected_failures=len(result.expectedFailures),
                  unexpected_successes=len(result.unexpectedSuccesses))
    write_json(Path(result_path), counts)
    return 0 if tests_passed(counts) else 1


def tests_passed(counts):
    return (counts.get("tests_run", 0) > 0 and
            all(counts.get(key, 0) == 0 for key in
                ("failures", "errors", "skipped", "unexpected_successes")))


def stop_group(process):
    # Kill the session even if its leader exited: grandchildren may still be alive.
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass  # Never wait indefinitely on an uninterruptible child.


def run_stage(command, log_path, timeout, env):
    started = time.monotonic()
    result = {"status": "failed", "command": command}
    process = None
    try:
        with log_path.open("wb") as log:
            process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=log,
                                       stderr=subprocess.STDOUT, start_new_session=True)
            result["returncode"] = process.wait(timeout=timeout)
            result["status"] = "passed" if result["returncode"] == 0 else "failed"
    except subprocess.TimeoutExpired:
        result["status"] = "timeout"
    except KeyboardInterrupt:
        result["status"] = "interrupted"
    except OSError as exc:
        result["error"] = str(exc)
    finally:
        if process is not None:
            stop_group(process)
        result["seconds"] = round(time.monotonic() - started, 3)
    return result


def metadata():
    def git(*args):
        try:
            result = subprocess.run(["git", *args], cwd=ROOT, capture_output=True,
                                    text=True, timeout=10)
            return result.stdout.strip() if result.returncode == 0 else None
        except (OSError, subprocess.TimeoutExpired):
            return None
    try:
        yaml_version = importlib.metadata.version("PyYAML")
    except importlib.metadata.PackageNotFoundError:
        yaml_version = None
    return dict(python=sys.version, executable=sys.executable, platform=platform.platform(),
                sqlite=sqlite3.sqlite_version, pyyaml=yaml_version,
                git_head=git("rev-parse", "HEAD"), git_status=git("status", "--porcelain"))


def scenario_modules():
    folders = ("os1_building", "os2_robot", "os3_mobility", "os4_iot", "os5_reliable")
    return sorted(str(path.relative_to(ROOT)) for folder in folders
                  for path in (ROOT / "src/edge/teams" / folder).glob("s[0-9]_*.py"))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="new artifact directory; must not already exist")
    parser.add_argument("--timeout", type=float, default=900, help="seconds per stage (default: 900)")
    parser.add_argument("--test-child", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    reason = unsupported_reason()
    if reason:
        print(reason, file=sys.stderr)
        return 2
    if args.timeout <= 0 or not math.isfinite(args.timeout):
        parser.error("--timeout must be a finite positive number")
    if args.test_child:
        return test_child(args.test_child)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    output = (args.output or ROOT / "data/verification" / f"{stamp}-{uuid.uuid4().hex[:8]}").resolve()
    try:
        output.mkdir(parents=True, exist_ok=False)
    except OSError as exc:
        print(f"Cannot create new output directory {output}: {exc}", file=sys.stderr)
        return 2
    summary = {"status": "failed", "environment": {}, "stages": {
        "unittest": {"status": "not_run"}, "scenarios": {"status": "not_run"}}}
    env = dict(os.environ, PYTHONPATH=str(ROOT / "src"))
    try:
        summary["environment"] = metadata()
        counts_path = output / "unittest-result.json"
        tests = run_stage([sys.executable, str(Path(__file__).resolve()), "--test-child", str(counts_path)],
                          output / "unittest.log", args.timeout, env)
        summary["stages"]["unittest"] = tests
        if counts_path.exists() or tests["status"] == "passed":
            try:
                counts = json.loads(counts_path.read_text(encoding="utf-8"))
                tests["counts"] = counts
                if tests["status"] == "passed" and not tests_passed(counts):
                    tests["status"] = "failed"
            except (OSError, ValueError, TypeError) as exc:
                tests.update(status="failed", error=f"Invalid unittest result: {exc}")
        if tests["status"] != "interrupted":
            modules = scenario_modules()
            summary["scenario_modules"] = modules
            if len(modules) != 25:
                summary["stages"]["scenarios"] = {"status": "failed", "error": f"Expected 25 scenario modules, found {len(modules)}"}
            else:
                summary["stages"]["scenarios"] = run_stage(
                    [sys.executable, str(ROOT / "scripts/run_all_scenarios.py")],
                    output / "scenarios.log", args.timeout, env)
        summary["status"] = "passed" if all(s["status"] == "passed" for s in summary["stages"].values()) else "failed"
    except KeyboardInterrupt:
        summary["error"] = "Interrupted"
    except Exception as exc:
        summary["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        write_json(output / "summary.json", summary)
    print(f"{summary['status']}: {output / 'summary.json'}")
    return 0 if summary["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
