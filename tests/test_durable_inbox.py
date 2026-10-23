"""Durable acceptance, atomic processing, and real process crash boundaries."""
import multiprocessing as mp
import os
import sqlite3
import tempfile
import time
import unittest
from contextlib import contextmanager
from pathlib import Path

from edge.core.ipc import StopFlag
from edge.core.models import SensorEvent
from edge.core.storage import Storage
from edge.decision import RuleEngine

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = str(ROOT / "sql" / "schema.sql")
RULES = [dict(name="hot", sensor="temperature", op=">", threshold=10,
              actuator="fan", command=100, ttl_s=15)]


def wait_until(predicate, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(0.025)
    raise AssertionError("condition did not become true before deadline")


def terminate_process(proc):
    if proc.is_alive():
        proc.terminate()
    proc.join(5)
    if proc.is_alive():
        proc.kill()
        proc.join(5)


class FailingStorage(Storage):
    @contextmanager
    def tx(self):
        with super().tx() as conn:
            yield conn
            # The real SQL statements have already executed, but COMMIT has not.
            raise RuntimeError("injected after SQL effects")


class BarrierStorage(Storage):
    """Test-only barriers surrounding the real transaction context manager."""
    def __init__(self, db, phase, pipe):
        super().__init__(db, SCHEMA, init=False)
        self.phase, self.pipe = phase, pipe

    def barrier(self):
        self.pipe.send(self.phase)
        self.pipe.recv()  # parent kills this process without releasing the barrier

    @contextmanager
    def tx(self):
        if self.phase == "before":
            self.barrier()
        with super().tx() as conn:
            yield conn
            if self.phase == "uncommitted":
                self.barrier()
        if self.phase == "committed":
            self.barrier()


def crash_worker(db, seq, phase, pipe):
    BarrierStorage(db, phase, pipe).process_inbox_event(seq, RuleEngine(RULES))


def recovery_worker(cfg, stop):
    if os.name == "posix":
        from edge.workers import processor_main
        processor_main(cfg, stop)
    else:
        storage = Storage(cfg["paths"]["db"], SCHEMA, init=False)
        while not stop.is_set():
            for row in storage.pending_inbox():
                storage.process_inbox_event(row["seq"], RuleEngine(RULES))
            stop.wait(0.02)


class DurableInboxTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = os.path.join(self.tmp.name, "node.db")
        self.storage = Storage(self.db, SCHEMA)
        self.engine = RuleEngine(RULES)

    def event(self, event_id="reading"):
        return SensorEvent("test-node", "temperature", 20, event_id=event_id)

    def assert_effects(self, ids):
        for table in ("sensor_events", "outbox", "edge_decisions"):
            rows = self.storage._read("SELECT event_id FROM " + table)
            self.assertEqual(sorted(r["event_id"] for r in rows), sorted(ids), table)
        report = self.storage.ingestion_report()
        self.assertTrue(report["consistent"], report)
        self.assertEqual(report["pending"], 0)
        self.assertEqual(report["completed"], len(ids))

    def test_duplicate_acceptance_and_replay_are_idempotent(self):
        event = self.event()
        self.assertTrue(self.storage.accept_event(event))
        self.assertFalse(self.storage.accept_event(event))
        row, = self.storage.pending_inbox()
        self.assertTrue(self.storage.process_inbox_event(row["seq"], self.engine))
        self.assertFalse(self.storage.process_inbox_event(row["seq"], self.engine))
        self.assertFalse(self.storage.accept_event(event))
        self.assert_effects([event.event_id])

    def test_exception_after_sql_rolls_back_all_effects(self):
        self.storage.accept_event(self.event())
        row, = self.storage.pending_inbox()
        broken = FailingStorage(self.db, SCHEMA, init=False)
        with self.assertRaisesRegex(RuntimeError, "after SQL"):
            broken.process_inbox_event(row["seq"], self.engine)
        for table in ("sensor_events", "outbox", "edge_decisions"):
            self.assertEqual(self.storage._read("SELECT COUNT(*) AS n FROM " + table)[0]["n"], 0)
        self.assertEqual(len(self.storage.pending_inbox()), 1)
        self.storage.process_inbox_event(row["seq"], self.engine)
        self.assert_effects(["reading"])

    def test_more_than_previous_queue_capacity_survives_restart(self):
        ids = ["reading-%04d" % i for i in range(625)]
        for event_id in ids:
            self.assertTrue(self.storage.accept_event(self.event(event_id)))
        self.storage = Storage(self.db, SCHEMA)
        self.assertEqual(self.storage.ingestion_report()["pending"], len(ids))
        while True:
            rows = self.storage.pending_inbox(limit=37)
            if not rows:
                break
            for row in rows:
                self.storage.process_inbox_event(row["seq"], self.engine)
        self.assert_effects(ids)

    def test_additive_initialization_preserves_legacy_data(self):
        legacy_db = os.path.join(self.tmp.name, "legacy.db")
        script = Path(SCHEMA).read_text(encoding="utf-8")
        # Preserve complete SQL statements, including comments with semicolons.
        conn = sqlite3.connect(legacy_db)
        try:
            statement = ""
            for line in script.splitlines(keepends=True):
                statement += line
                if sqlite3.complete_statement(statement):
                    if "runtime_inbox" not in statement.lower():
                        conn.execute(statement)
                    statement = ""
        finally:
            conn.close()
        legacy = Storage(legacy_db, SCHEMA, init=False)
        legacy.insert_event_with_outbox(self.event("legacy"))
        upgraded = Storage(legacy_db, SCHEMA)
        Storage(legacy_db, SCHEMA)  # migration is safe to repeat
        self.assertEqual(upgraded.counts()["events"], 1)
        self.assertTrue(upgraded.accept_event(self.event("new")))
        row, = upgraded.pending_inbox()
        upgraded.process_inbox_event(row["seq"], self.engine)
        self.assertEqual(upgraded.counts()["events"], 2)

    def test_null_id_is_rejected_instead_of_reported_as_duplicate(self):
        event = self.event()
        event.event_id = None
        with self.assertRaises(sqlite3.IntegrityError):
            self.storage.accept_event(event)
        self.assertEqual(self.storage.ingestion_report()["accepted"], 0)

    def test_invalid_reading_constraint_does_not_complete_inbox(self):
        event = self.event()
        event.value = None
        self.assertTrue(self.storage.accept_event(event))
        row, = self.storage.pending_inbox()
        with self.assertRaises(sqlite3.IntegrityError):
            self.storage.process_inbox_event(row["seq"], self.engine)
        report = self.storage.ingestion_report()
        self.assertEqual(report["pending"], 1)
        self.assertEqual(report["completed"], 0)
        for table in ("sensor_events", "outbox", "edge_decisions"):
            self.assertEqual(self.storage._read("SELECT COUNT(*) AS n FROM " + table)[0]["n"], 0)

    def test_report_detects_equal_counts_with_wrong_ids(self):
        self.storage.accept_event(self.event())
        row, = self.storage.pending_inbox()
        self.storage.process_inbox_event(row["seq"], self.engine)
        with self.storage.tx() as conn:
            conn.execute("UPDATE outbox SET event_id='unrelated'")
        report = self.storage.ingestion_report()
        self.assertEqual(report["accepted"], report["completed"])
        self.assertFalse(report["consistent"], report)

    def test_sigkill_at_transaction_boundaries_then_actual_processor_restart(self):
        ctx = mp.get_context("spawn")
        completed_ids = []
        for phase in ("before", "uncommitted", "committed"):
            with self.subTest(phase=phase):
                event_id = "crash-" + phase
                self.storage.accept_event(self.event(event_id))
                row, = self.storage.pending_inbox()
                parent, child = ctx.Pipe()
                crashed = ctx.Process(target=crash_worker,
                                      args=(self.db, row["seq"], phase, child))
                crashed.start()
                child.close()
                try:
                    self.assertTrue(parent.poll(10), "child never reached " + phase)
                    self.assertEqual(parent.recv(), phase)
                    # Other connections see all three effects only after COMMIT.
                    visible = self.storage._read("SELECT event_id FROM sensor_events WHERE event_id=?", (event_id,))
                    self.assertEqual(bool(visible), phase == "committed")
                    crashed.kill()
                    crashed.join(5)
                    self.assertIsNotNone(crashed.exitcode)
                    self.assertNotEqual(crashed.exitcode, 0)
                finally:
                    terminate_process(crashed)
                    parent.close()
                stop = StopFlag(ctx)
                cfg = {"paths": {"db": self.db, "schema": SCHEMA}, "rules": RULES}
                restarted = ctx.Process(target=recovery_worker, args=(cfg, stop))
                restarted.start()
                try:
                    wait_until(lambda: self.storage.ingestion_report()["pending"] == 0)
                    stop.set()
                    restarted.join(5)
                    self.assertEqual(restarted.exitcode, 0)
                finally:
                    terminate_process(restarted)
                completed_ids.append(event_id)
                self.assert_effects(completed_ids)
