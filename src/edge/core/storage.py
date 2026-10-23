"""SQLite storage: WAL mode, atomic transactions, durable outbox, online backup."""
import json
import os
import sqlite3
import time
from contextlib import contextmanager

from edge.core.models import SensorEvent
from edge.decision import dispatch


class Storage:
    def __init__(self, db_path, schema_path, init=True):
        self.db_path = db_path
        self.schema_path = schema_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        if init:
            self.init_schema()

    # ---- connection helpers (one short-lived connection per call = thread/process safe) ----
    def _connect(self):
        conn = sqlite3.connect(self.db_path, timeout=5.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    @contextmanager
    def tx(self):
        """All-or-nothing transaction."""
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.execute("COMMIT")
        except BaseException:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        finally:
            conn.close()

    def _read(self, sql, params=()):
        conn = self._connect()
        try:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]
        finally:
            conn.close()

    def init_schema(self):
        with open(self.schema_path, encoding="utf-8") as f:
            script = f.read()
        conn = self._connect()
        try:
            conn.executescript(script)
        finally:
            conn.close()

    def journal_mode(self):
        return self._read("PRAGMA journal_mode")[0]["journal_mode"]

    # ---- events + outbox ----
    def accept_event(self, event):
        """Commit an event to the runtime inbox; return False for a repeated ID."""
        with self.tx() as c:
            cur = c.execute(
                "INSERT INTO runtime_inbox (event_id,payload) VALUES (?,?) "
                "ON CONFLICT(event_id) DO NOTHING",
                (event.event_id, json.dumps(event.to_dict())))
            return cur.rowcount == 1

    def pending_inbox(self, limit=50):
        """Return the oldest unprocessed handoffs from the durable inbox."""
        return self._read(
            "SELECT seq,payload FROM runtime_inbox WHERE done=0 ORDER BY seq LIMIT ?",
            (limit,))

    def process_inbox_event(self, seq, engine):
        """Commit one pending row and all its database effects atomically.

        Dispatch is the local simulation only. This transaction does not provide
        an exactly-once guarantee for an external physical actuator.
        """
        with self.tx() as c:
            row = c.execute(
                "SELECT event_id,payload FROM runtime_inbox WHERE seq=? AND done=0",
                (seq,)).fetchone()
            if row is None:
                return False
            event = SensorEvent.from_dict(json.loads(row["payload"]))
            if event.event_id != row["event_id"]:
                raise ValueError("runtime inbox payload event_id does not match its key")
            event.received_at = time.time()
            cur = c.execute(
                "INSERT INTO sensor_events "
                "(event_id,node_id,sensor,value,unit,observed_at,received_at) VALUES (?,?,?,?,?,?,?) "
                "ON CONFLICT(event_id) DO NOTHING",
                (event.event_id, event.node_id, event.sensor, event.value,
                 event.unit, event.observed_at, event.received_at))
            if cur.rowcount:
                c.execute("INSERT INTO outbox (event_id,payload,enqueued_at) VALUES (?,?,?)",
                          (event.event_id, json.dumps(event.to_dict()), time.time()))
                for d in engine.evaluate(event):
                    status = dispatch(d)
                    c.execute(
                        "INSERT INTO edge_decisions (decision_id,event_id,rule,actuator,command_value,"
                        "issued_mono,expires_mono,status,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                        (d.decision_id, d.event_id, d.rule, d.actuator, d.command_value,
                         d.issued_mono, d.expires_mono, status, d.created_at))
            c.execute("UPDATE runtime_inbox SET done=1 WHERE seq=?", (seq,))
            return True

    def ingestion_report(self):
        """Read inbox conservation and ID relationships in one SQLite snapshot.

        Standalone sensor rows need not belong to the shared runtime inbox.
        Counts alone cannot detect missing rows replaced by unrelated IDs.
        """
        row = self._read("""
            SELECT
              (SELECT COUNT(*) FROM runtime_inbox) AS accepted,
              (SELECT COUNT(*) FROM runtime_inbox WHERE done=0) AS pending,
              (SELECT COUNT(*) FROM runtime_inbox WHERE done=1) AS completed,
              NOT EXISTS (
                SELECT 1 FROM runtime_inbox i
                LEFT JOIN sensor_events e ON e.event_id=i.event_id
                LEFT JOIN outbox o ON o.event_id=i.event_id
                WHERE i.done NOT IN (0,1)
                   OR (i.done=1 AND (e.event_id IS NULL OR o.event_id IS NULL))
              ) AND NOT EXISTS (
                SELECT 1 FROM outbox o
                LEFT JOIN sensor_events e ON e.event_id=o.event_id
                LEFT JOIN upstream_sink s ON s.event_id=o.event_id
                WHERE e.event_id IS NULL
                   OR (o.sent_at IS NOT NULL AND s.event_id IS NULL)
                   OR (o.sent_at IS NULL AND s.event_id IS NOT NULL)
              ) AND NOT EXISTS (
                SELECT 1 FROM upstream_sink s
                LEFT JOIN outbox o ON o.event_id=s.event_id
                WHERE o.event_id IS NULL
              ) AND NOT EXISTS (
                SELECT 1 FROM edge_decisions d
                LEFT JOIN sensor_events e ON e.event_id=d.event_id
                WHERE e.event_id IS NULL
              ) AS consistent
        """)[0]
        row["consistent"] = bool(row["consistent"])
        return row

    def insert_event_with_outbox(self, event):
        """Store the event AND enqueue it in the outbox atomically.
        Returns False if the event_id was already stored (duplicate ignored)."""
        with self.tx() as c:
            cur = c.execute(
                "INSERT OR IGNORE INTO sensor_events "
                "(event_id,node_id,sensor,value,unit,observed_at,received_at) VALUES (?,?,?,?,?,?,?)",
                (event.event_id, event.node_id, event.sensor, event.value,
                 event.unit, event.observed_at, event.received_at))
            if cur.rowcount == 0:
                return False
            c.execute("INSERT INTO outbox (event_id,payload,enqueued_at) VALUES (?,?,?)",
                      (event.event_id, json.dumps(event.to_dict()), time.time()))
            return True

    def outbox_pending(self):
        return self._read("SELECT COUNT(*) AS n FROM outbox WHERE sent_at IS NULL")[0]["n"]

    def drain_outbox_to_sink(self, batch_size=50):
        """Deliver one batch to the (mock) upstream and mark it sent, in ONE transaction.
        The sink's PRIMARY KEY makes redelivery idempotent. Returns rows delivered."""
        with self.tx() as c:
            rows = c.execute("SELECT id,event_id,payload FROM outbox "
                             "WHERE sent_at IS NULL ORDER BY id LIMIT ?", (batch_size,)).fetchall()
            now = time.time()
            for r in rows:
                c.execute("INSERT OR IGNORE INTO upstream_sink (event_id,payload,received_at) VALUES (?,?,?)",
                          (r["event_id"], r["payload"], now))
                c.execute("UPDATE outbox SET sent_at=? WHERE id=?", (now, r["id"]))
            return len(rows)

    def conservation_report(self):
        """Event conservation: every stored event is either in the sink or still pending."""
        row = self._read("""
            SELECT
              (SELECT COUNT(*) FROM sensor_events) AS events,
              (SELECT COUNT(*) FROM upstream_sink) AS sink,
              (SELECT COUNT(*) FROM outbox WHERE sent_at IS NULL) AS pending
        """)[0]
        row["conserved"] = row["events"] == row["sink"] + row["pending"]
        return row

    # ---- decisions ----
    def insert_decision(self, d):
        with self.tx() as c:
            c.execute(
                "INSERT INTO edge_decisions (decision_id,event_id,rule,actuator,command_value,"
                "issued_mono,expires_mono,status,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (d.decision_id, d.event_id, d.rule, d.actuator, d.command_value,
                 d.issued_mono, d.expires_mono, d.status, d.created_at))

    def set_decision_status(self, decision_id, status):
        with self.tx() as c:
            c.execute("UPDATE edge_decisions SET status=? WHERE decision_id=?", (status, decision_id))

    # ---- process health ----
    def upsert_health(self, h):
        with self.tx() as c:
            c.execute(
                "INSERT INTO process_health (name,pid,state,rss_kb,cpu_pct,ctx_voluntary,"
                "ctx_involuntary,restarts,updated_at) VALUES (?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(name) DO UPDATE SET pid=excluded.pid,state=excluded.state,"
                "rss_kb=excluded.rss_kb,cpu_pct=excluded.cpu_pct,ctx_voluntary=excluded.ctx_voluntary,"
                "ctx_involuntary=excluded.ctx_involuntary,restarts=excluded.restarts,"
                "updated_at=excluded.updated_at",
                (h.name, h.pid, h.state, h.rss_kb, h.cpu_pct, h.ctx_voluntary,
                 h.ctx_involuntary, h.restarts, h.updated_at))

    def list_health(self):
        return self._read("SELECT * FROM process_health ORDER BY name")

    # ---- key/value (WAN state lives here so every process sees it) ----
    def kv_get(self, key, default=None):
        rows = self._read("SELECT value FROM kv WHERE key=?", (key,))
        return rows[0]["value"] if rows else default

    def kv_set(self, key, value):
        with self.tx() as c:
            c.execute("INSERT INTO kv (key,value) VALUES (?,?) "
                      "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))

    def wan_online(self):
        return self.kv_get("wan_online", "1") == "1"

    def set_wan_online(self, online):
        self.kv_set("wan_online", "1" if online else "0")

    # ---- misc ----
    def counts(self):
        q = lambda t: self._read(f"SELECT COUNT(*) AS n FROM {t}")[0]["n"]
        return {"events": q("sensor_events"), "decisions": q("edge_decisions"),
                "sink": q("upstream_sink")}

    def backup(self, dest_path):
        """Safe online backup (SQLite backup API) + integrity check. Returns True if ok."""
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        src = self._connect()
        dst = sqlite3.connect(dest_path)
        try:
            src.backup(dst)
            return dst.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        finally:
            dst.close()
            src.close()
