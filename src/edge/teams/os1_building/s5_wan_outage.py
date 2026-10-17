"""OS1-5: Signature WAN Outage & Offline Outbox Queueing.

Simulates a WAN outage without changing the real network interface. Sensor events
are atomically stored with outbox entries while WAN is down; after restoring the
mock WAN, the worker drains batches to the idempotent upstream sink.
"""
import os
import sys
import tempfile
import time
from pathlib import Path

from edge.core.models import SensorEvent
from edge.core.storage import Storage

ROOT = Path(__file__).resolve().parents[4]
SCHEMA = ROOT / "sql" / "schema.sql"
NODE_ID = "EDGE_NODE_OS1_CONVENSIA"


def run(event_count=120, batch_size=25, db_path=None):
    """Run a fast outage/recovery simulation; return (ok, report_lines)."""
    if event_count < 1 or batch_size < 1:
        raise ValueError("event_count and batch_size must be positive")
    temp_dir = tempfile.TemporaryDirectory() if db_path is None else None
    try:
        path = db_path or os.path.join(temp_dir.name, "os1_s5.db")
        db = Storage(path, str(SCHEMA))
        db.set_wan_online(False)
        for tick in range(event_count):
            event = SensorEvent(NODE_ID, "INDOOR_CO2_PPM", 600.0 + (tick % 500), "ppm",
                                observed_at=time.time() + tick, received_at=time.time())
            db.insert_event_with_outbox(event)

        queued_during_outage = db.outbox_pending()
        conservation_while_offline = db.conservation_report()
        # Restore the mock WAN and drain in bounded batches, as the sync worker does.
        db.set_wan_online(True)
        delivered = 0
        while db.outbox_pending() > 0:
            delivered += db.drain_outbox_to_sink(batch_size=batch_size)
        report = db.conservation_report()
        counts = db.counts()
        ok = (queued_during_outage == event_count and
              conservation_while_offline["conserved"] and
              delivered == event_count and report["conserved"] and
              report["sink"] == event_count and report["pending"] == 0 and
              counts["events"] == event_count)
        return ok, [
            f"mock WAN disconnected: queued {queued_during_outage}/{event_count} events locally",
            f"WAN restored: delivered {delivered} event(s) in batches of at most {batch_size}",
            f"conservation: events={report['events']}, upstream sink={report['sink']}, pending={report['pending']}",
            f"no data loss / no duplicate sink rows: {report['conserved'] and report['sink'] == event_count}",
            "this is a fast functional simulation; the 10-minute duration belongs in the live demo",
        ]
    finally:
        if temp_dir is not None:
            temp_dir.cleanup()


def main():
    ok, lines = run()
    print(f"[{'PASS' if ok else 'FAIL'}] OS1-5 WAN outage & offline outbox queueing")
    for line in lines:
        print("      ", line)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
