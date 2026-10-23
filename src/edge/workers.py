"""Worker process entry points: SensorGen, Processor, HealthMon."""
import json
import logging
import random
import signal
import time

from edge.core.models import ProcessHealth, SensorEvent
from edge.core.procfs import ProcSampler
from edge.core.storage import Storage
from edge.decision import RuleEngine


def _init(name):
    signal.signal(signal.SIGINT, signal.SIG_IGN)   # supervisor handles Ctrl+C
    logging.basicConfig(level=logging.INFO, format=f"%(asctime)s [{name}] %(message)s")
    return logging.getLogger(name)


def sensor_gen_main(cfg, stop):
    _init("SensorGen")
    storage = Storage(cfg["paths"]["db"], cfg["paths"]["schema"], init=False)
    rng = random.Random()
    node = cfg["node"]["id"]
    while not stop.is_set():
        for s in cfg["sensor"]["streams"]:
            if stop.is_set():
                break
            value = s["base"] + rng.gauss(0, s.get("noise", 0))
            if rng.random() < s.get("spike_prob", 0):
                value = s["spike_value"]
            ev = SensorEvent(node_id=node, sensor=s["name"], value=round(value, 2), unit=s.get("unit", ""))
            storage.accept_event(ev)
        stop.wait(cfg["sensor"]["interval_s"])


def processor_main(cfg, stop):
    log = _init("Processor")
    storage = Storage(cfg["paths"]["db"], cfg["paths"]["schema"], init=False)
    engine = RuleEngine(cfg["rules"])
    drain_deadline = None
    while True:
        if stop.is_set() and drain_deadline is None:
            drain_deadline = time.monotonic() + 3.0
        if drain_deadline is not None and time.monotonic() >= drain_deadline:
            break
        rows = storage.pending_inbox(limit=50)
        if not rows:
            if drain_deadline is not None:
                break
            stop.wait(0.05)
            continue
        for row in rows:
            if stop.is_set() and drain_deadline is None:
                drain_deadline = time.monotonic() + 3.0
            if drain_deadline is not None and time.monotonic() >= drain_deadline:
                break
            storage.process_inbox_event(row["seq"], engine)
    log.info("exiting cleanly")


def health_main(cfg, stop):
    _init("HealthMon")
    storage = Storage(cfg["paths"]["db"], cfg["paths"]["schema"], init=False)
    sampler = ProcSampler()
    while not stop.is_set():
        try:
            with open(cfg["paths"]["pidfile"], encoding="utf-8") as f:
                pids = json.load(f)
        except (FileNotFoundError, ValueError):
            pids = {}
        for name, info in pids.items():
            m = sampler.sample(info["pid"])
            if m is None:
                continue
            storage.upsert_health(ProcessHealth(
                name=name, pid=info["pid"], state=m["state"], rss_kb=m["rss_kb"],
                cpu_pct=m["cpu_pct"], ctx_voluntary=m["ctx_voluntary"],
                ctx_involuntary=m["ctx_involuntary"], restarts=info.get("restarts", 0)))
        stop.wait(cfg["health"]["interval_s"])
