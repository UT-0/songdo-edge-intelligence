"""Real supervised workers: crash recovery, WAN backlog, and runtime restart."""
import json
import os
import signal
import socket
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path

import yaml

from edge.core.models import SensorEvent
from edge.core.storage import Storage
from tests.test_durable_inbox import wait_until

ROOT = Path(__file__).resolve().parents[1]


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def call(port, path, method="GET"):
    req = urllib.request.Request("http://127.0.0.1:%s%s" % (port, path), method=method)
    with urllib.request.urlopen(req, timeout=1) as response:
        return json.loads(response.read())


@unittest.skipUnless(os.name == "posix", "runtime requires Linux /proc and POSIX signals")
class TestOfflineDemo(unittest.TestCase):
    def setUp(self):
        from edge.supervisor import Supervisor
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        with open(ROOT / "config" / "node.yaml", encoding="utf-8") as stream:
            self.cfg = yaml.safe_load(stream)
        self.cfg["network"]["api_port"] = free_port()
        self.cfg["sensor"]["interval_s"] = 0.04
        self.cfg["sync"].update(interval_s=0.05, batch_size=100)
        self.cfg["supervisor"]["restart_delay_s"] = 0.01
        self.cfg["paths"] = dict(
            db=os.path.join(self.tmp.name, "node.db"),
            backups=os.path.join(self.tmp.name, "backups"),
            pidfile=os.path.join(self.tmp.name, "pids.json"),
            schema=str(ROOT / "sql" / "schema.sql"),
            static=str(ROOT / "src" / "edge" / "ui"),
            socket=os.path.join(self.tmp.name, "node.sock"))
        self.supervisors = []
        self.addCleanup(self.cleanup_workers)
        self.Supervisor = Supervisor
        self.storage = Storage(self.cfg["paths"]["db"], self.cfg["paths"]["schema"])

    def cleanup_workers(self):
        for supervisor in self.supervisors:
            try:
                supervisor.stop()
            finally:
                for proc in supervisor.procs.values():
                    if proc.is_alive():
                        proc.kill()
                    proc.join(5)
                self.assertTrue(all(not p.is_alive() for p in supervisor.procs.values()))

    def start_runtime(self):
        supervisor = self.Supervisor(self.cfg)
        self.supervisors.append(supervisor)
        supervisor.start()
        def ready():
            try:
                return call(self.cfg["network"]["api_port"], "/api/status")
            except (OSError, ValueError):
                return False
        wait_until(ready)
        return supervisor

    def test_wan_cut_processor_sigkill_restore_conserves_ids(self):
        supervisor = self.start_runtime()
        port = self.cfg["network"]["api_port"]
        call(port, "/api/wan/cut", "POST")
        wait_until(lambda: self.storage.outbox_pending() >= 20)
        before = self.storage.ingestion_report()["accepted"]
        old = supervisor.procs["Processor"]
        os.kill(old.pid, signal.SIGKILL)
        old.join(5)
        supervisor._reap_and_restart()
        self.assertNotEqual(supervisor.procs["Processor"].pid, old.pid)
        self.assertEqual(supervisor.restarts["Processor"], 1)
        wait_until(lambda: self.storage.ingestion_report()["completed"] > before + 10)
        supervisor.producer_stop_event.set()
        supervisor.procs["SensorGen"].join(5)
        wait_until(lambda: self.storage.ingestion_report()["pending"] == 0)
        ids = {r["event_id"] for r in self.storage._read("SELECT event_id FROM runtime_inbox")}
        call(port, "/api/wan/restore", "POST")
        wait_until(lambda: self.storage.outbox_pending() == 0)
        supervisor.stop()
        self.assertTrue(self.storage.ingestion_report()["consistent"])
        for table in ("sensor_events", "outbox", "upstream_sink"):
            self.assertEqual({r["event_id"] for r in self.storage._read("SELECT event_id FROM " + table)}, ids)

    def test_full_runtime_restart_replays_pending_ids_and_shutdown_is_bounded(self):
        supervisor = self.start_runtime()
        proc = supervisor.procs["Processor"]
        os.kill(proc.pid, signal.SIGKILL)
        proc.join(5)
        supervisor.producer_stop_event.set()
        supervisor.procs["SensorGen"].join(5)
        ids = {"restart-%04d" % i for i in range(550)}
        for event_id in ids:
            self.storage.accept_event(SensorEvent("restart-node", "ROOM_TEMP_C", 23, event_id=event_id))
        pending = {json.loads(r["payload"])["event_id"] for r in self.storage.pending_inbox(limit=10000)}
        self.assertTrue(ids <= pending)
        started = time.monotonic()
        supervisor.stop()
        self.assertLess(time.monotonic() - started, 12, "shutdown blocked without a processor")
        self.assertTrue(all(not p.is_alive() for p in supervisor.procs.values()))
        self.assertTrue(ids <= {json.loads(r["payload"])["event_id"] for r in self.storage.pending_inbox(limit=10000)})
        restarted = self.start_runtime()
        restarted.producer_stop_event.set()
        restarted.procs["SensorGen"].join(5)
        wait_until(lambda: self.storage.ingestion_report()["pending"] == 0)
        wait_until(lambda: self.storage.outbox_pending() == 0)
        restarted.stop()
        for table in ("sensor_events", "outbox", "upstream_sink"):
            found = {r["event_id"] for r in self.storage._read("SELECT event_id FROM " + table)}
            self.assertTrue(pending <= found, table)
        report = self.storage.ingestion_report()
        self.assertEqual(report["accepted"], report["completed"])
        self.assertTrue(report["consistent"], report)


if __name__ == "__main__":
    unittest.main()
