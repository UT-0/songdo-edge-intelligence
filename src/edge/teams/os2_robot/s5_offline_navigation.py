"""OS2-5: Autonomous Offline Pathway Navigation

Mission : The robot keeps navigating and avoiding obstacles while the WAN is cut. Telemetry
          is logged to the durable outbox and delivered after the link comes back.
Concept : Local control never waits for the network. The navigation loop (50 ms, absolute
          monotonic deadlines) only talks to local SQLite. A separate sync thread drains the
          outbox, but only while the WAN flag says "online". Zero loss is checked by event
          conservation: events stored == events delivered, no duplicates.

Owner   : (write names here)
Test    : tests/os2/test_s5_offline_navigation.py
Run     : PYTHONPATH=src python -m edge.teams.os2_robot.s5_offline_navigation [--offline 600]
          (--offline is the outage length in seconds. Default 3; use 600 for the 10-minute
          signature run. All lengths are counted in 50 ms ticks, not wall time.)

Simulation (all values SIMULATED): every 20th tick a 3-tick obstacle at 0.5 m appears,
otherwise the path is clear at 2.5 m. The loop reuses the OS2-3 SafetyLatch and the shared
RuleEngine with the e-stop rule from config/os2.yaml. Phases: online -> WAN cut -> restored.
"""
import argparse
import os
import sys
import tempfile
import threading
import time

from edge.core.config import load_config
from edge.core.models import SensorEvent
from edge.core.storage import Storage
from edge.decision import RuleEngine
from edge.teams.os2_robot.s3_estop_ttl import SafetyLatch

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
PERIOD_S = 0.05
CLEAR_M, BLOCKED_M = 2.5, 0.5


def _distance(i):
    return BLOCKED_M if (i % 20) in (10, 11, 12) else CLEAR_M


def _sync_loop(st, stop):
    """The upstream sync worker: drains the outbox only while the WAN is online."""
    while not stop.is_set():
        if st.wan_online() and st.drain_outbox_to_sink(200):
            continue
        time.sleep(0.05)


def run(online_s=1.0, offline_s=3.0, restored_s=2.0):
    """Returns (ok, report_lines)."""
    cfg = load_config(os.path.join(ROOT, "config", "os2.yaml"))
    engine = RuleEngine(cfg["rules"])
    node = cfg["node"]["id"]
    phases = [("online", int(online_s / PERIOD_S)), ("WAN cut", int(offline_s / PERIOD_S)),
              ("restored", int(restored_s / PERIOD_S))]
    per = {name: {"ticks": 0, "episodes": 0, "engaged": 0, "unsafe": 0} for name, _ in phases}

    with tempfile.TemporaryDirectory() as tmp:
        st = Storage(os.path.join(tmp, "os2_nav.db"), cfg["paths"]["schema"])
        st.set_wan_online(True)
        stop = threading.Event()
        syncer = threading.Thread(target=_sync_loop, args=(st, stop), daemon=True)
        syncer.start()

        latch = SafetyLatch()
        stamps, i, prev_blocked = [], 0, False
        base = {}
        deadline = time.monotonic()
        for name, n_ticks in phases:
            if name == "WAN cut":
                st.set_wan_online(False)
            elif name == "restored":
                base["end_pending"], base["end_sink"] = st.outbox_pending(), st.counts()["sink"]
                st.set_wan_online(True)
            for k in range(n_ticks):
                delay = deadline - time.monotonic()
                if delay > 0:
                    time.sleep(delay)
                deadline += PERIOD_S
                now = time.monotonic()
                stamps.append(now)

                d = _distance(i)
                ev = SensorEvent(node_id=node, sensor="LIDAR_PROXIMITY_M", value=d, unit="m")
                ev.received_at = time.time()
                st.insert_event_with_outbox(ev)           # durable first, network never involved
                blocked = d < 0.8
                p = per[name]
                p["ticks"] += 1
                if blocked and not prev_blocked:
                    p["episodes"] += 1
                if latch.on_proximity(d):
                    p["engaged"] += 1
                for dec in engine.evaluate(ev, now):
                    st.insert_decision(dec)
                    st.set_decision_status(dec.decision_id, latch.submit(dec, now))
                latch.try_release(d)
                velocity = 0.0 if latch.engaged else 0.5
                if blocked and velocity != 0:
                    p["unsafe"] += 1                      # robot moved with an obstacle in front
                prev_blocked = blocked
                i += 1
                if name == "WAN cut" and k == min(10, n_ticks // 2):
                    base["cut_pending"], base["cut_sink"] = st.outbox_pending(), st.counts()["sink"]

        # nav loop is over: give the sync thread time to drain what is left
        t_end = time.monotonic() + 15 + st.outbox_pending() / 200
        while st.outbox_pending() > 0 and time.monotonic() < t_end:
            time.sleep(0.05)
        stop.set()
        syncer.join(5)

        rep = st.conservation_report()
        conn = st._connect()
        try:
            distinct = conn.execute("SELECT COUNT(DISTINCT event_id) FROM upstream_sink").fetchone()[0]
        finally:
            conn.close()

    gaps = [b - a for a, b in zip(stamps, stamps[1:])]
    max_gap_ms = 1000 * max(gaps)
    cut = per["WAN cut"]
    checks = {
        f"{cut['ticks']} ticks ran during the WAN cut, longest gap between ticks {max_gap_ms:.0f} ms "
        f"(limit {PERIOD_S * 6000:.0f} ms)": cut["ticks"] == phases[1][1] and max_gap_ms < PERIOD_S * 6000,
        "obstacle avoidance identical in every phase (every obstacle latched, robot never moved blocked): "
        + ", ".join(f"{n}: {v['engaged']}/{v['episodes']}" for n, v in per.items()):
            all(v["episodes"] >= 1 and v["engaged"] == v["episodes"] and v["unsafe"] == 0 for v in per.values()),
        f"outbox grew during the cut ({base.get('cut_pending')} -> {base.get('end_pending')} pending)":
            base.get("end_pending", 0) > base.get("cut_pending", 10 ** 9),
        f"nothing delivered during the cut (sink stayed at {base.get('cut_sink')})":
            base.get("end_sink") == base.get("cut_sink"),
        f"after restore the outbox drained to {rep['pending']} pending": rep["pending"] == 0,
        f"event conservation: {rep['events']} stored = {rep['sink']} delivered, {distinct} distinct (no duplicates)":
            rep["conserved"] and rep["events"] == rep["sink"] == distinct and rep["events"] == len(stamps),
    }
    return all(checks.values()), [f"{'ok ' if v else 'FAILED '}{k}" for k, v in checks.items()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", type=float, default=3.0, help="WAN outage length in seconds (600 = 10 min)")
    args = ap.parse_args()
    ok, lines = run(offline_s=args.offline)
    print(f"[{'PASS' if ok else 'FAIL'}] OS2-5 Autonomous offline pathway navigation")
    for line in lines:
        print("      ", line)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
