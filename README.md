# Songdo Edge Intelligence (OS course project)

A multi-process Linux edge node that keeps working when the WAN is cut, then drains its durable
outbox with zero lost events. Python 3.12 + SQLite (WAL) + standard library (plus `pyyaml`).

The handbook defines **5 themes (OS1 to OS5) x 5 scenarios = 25 scenarios**. All 25 share one core.

## Quickstart
```bash
bash scripts/preflight.sh                 # check the machine
bash scripts/setup.sh                     # .venv + dependencies + database
PYTHONPATH=src python -m unittest discover -s tests -v
bash scripts/start_demo.sh OS1            # theme OS1 -> http://127.0.0.1:8001  (OS2 -> 8002 ... OS5 -> 8005)
bash scripts/start_demo.sh                # generic node  -> http://127.0.0.1:8000
```
In the dashboard: **Simulate WAN Internet Cut** -> events keep arriving, *Outbox queued* grows.
**Restore WAN Connection** -> backlog drains, *Conserved* stays `yes`.

## How it works
```
SensorGen --(BoundedQueue 500, drop_oldest)--> Processor --> SQLite (events, decisions, outbox)
HealthMon (/proc -> process_health)                |
API (http.server dashboard, /api/status, /api/wan/*)   SyncWorker (drains outbox only while WAN online)
Supervisor starts, monitors, restarts and cleanly stops everything.
```

## Layout: what is shared, what belongs to a scenario
```
config/node.yaml, os1.yaml ... os5.yaml   one config per theme (node id, sensors, rules, port, db)
sql/schema.sql                            SHARED tables
src/edge/core/                            SHARED core (models, ipc, storage, procfs, config)
src/edge/supervisor.py, workers.py, sync_worker.py, decision.py, api_server.py   SHARED pipeline
src/edge/teams/os1_building/ ... os5_reliable/    ONE FILE PER SCENARIO (25 files)
tests/test_core.py, test_pipeline.py, test_configs.py   shared tests
tests/os1/ ... tests/os5/                 scenario tests (create test_<scenario>.py)
scripts/, systemd/, container/            ops
```
**Shared files:** core owners only (others: open a PR). `config/*.yaml` and `schema.sql`: small
changes only, announce in the group chat. **Your scenario:** edit only your scenario file, its test,
and its report section.

Values in the theme configs marked ASSUMED (simulated sensor ranges, the OS3 pedestrian threshold,
OS3/OS5 TTLs) are not given in the handbook: confirm them with your team.

## The 25 tasks (fill in the owner column)
| ID | Scenario | File | Owner |
|---|---|---|---|
| OS1-1 | Local Room Sensor Ingestion & Cached Inventory | `src/edge/teams/os1_building/s1_ingestion.py` | |
| OS1-2 | Competing Occupancy Writers & Race Condition Demonstration | `src/edge/teams/os1_building/s2_race_condition.py` | |
| OS1-3 | Local Ventilation Rule & Damper Actuator Dispatch | `src/edge/teams/os1_building/s3_ventilation_rule.py` | |
| OS1-4 | Contention Profiling & Resource Sampling | `src/edge/teams/os1_building/s4_contention_profiling.py` | |
| OS1-5 | Signature WAN Outage & Offline Outbox Queueing | `src/edge/teams/os1_building/s5_wan_outage.py` | |
| OS2-1 | Multi-Process Robot Architecture & IPC Topology | `src/edge/teams/os2_robot/s1_robot_ipc_topology.py` | |
| OS2-2 | Periodic Monotonic Deadlines & Jitter Measurement | `src/edge/teams/os2_robot/s2_jitter.py` | |
| OS2-3 | Obstacle Proximity E-Stop & Actuator Command Expiry | `src/edge/teams/os2_robot/s3_estop_ttl.py` | |
| OS2-4 | Worker Crash & Supervised Automatic Restart | `src/edge/teams/os2_robot/s4_crash_restart.py` | |
| OS2-5 | Autonomous Offline Pathway Navigation | `src/edge/teams/os2_robot/s5_offline_navigation.py` | |
| OS3-1 | Incheon Bus Stop Context & Vehicle Influx Stream | `src/edge/teams/os3_mobility/s1_bus_stop_context.py` | |
| OS3-2 | Priority-Aware Bounded Queue Processing | `src/edge/teams/os3_mobility/s2_priority_queue.py` | |
| OS3-3 | Overload Experiment & Drop Policy Verification | `src/edge/teams/os3_mobility/s3_overload_drop.py` | |
| OS3-4 | Transactional State Update & Version Guarding | `src/edge/teams/os3_mobility/s4_versioned_transactions.py` | |
| OS3-5 | Offline Variable Speed Sign Dispatch & Event Replay | `src/edge/teams/os3_mobility/s5_speed_sign_replay.py` | |
| OS4-1 | Heterogeneous Multi-Stream Sensor Ingestion | `src/edge/teams/os4_iot/s1_multistream_ingestion.py` | |
| OS4-2 | Event-Time vs. Receipt-Time Handling | `src/edge/teams/os4_iot/s2_event_vs_receipt_time.py` | |
| OS4-3 | Dust Suppression Mist Cannon Relay Actuation | `src/edge/teams/os4_iot/s3_mist_cannon.py` | |
| OS4-4 | Scheduled Database Backup via systemd Timer / Cron | `src/edge/teams/os4_iot/s4_scheduled_backup.py` | |
| OS4-5 | WAN Outage Backlog Drain & AirKorea Baseline Benchmark | `src/edge/teams/os4_iot/s5_backlog_drain.py` | |
| OS5-1 | Health Check Architecture & Readiness State Machine | `src/edge/teams/os5_reliable/s1_health_probes.py` | |
| OS5-2 | Disposable Worker Kill & Preserved State Recovery | `src/edge/teams/os5_reliable/s2_worker_kill_recovery.py` | |
| OS5-3 | Deadlock Detection & Mutex Timeout Recovery | `src/edge/teams/os5_reliable/s3_deadlock_timeout.py` | |
| OS5-4 | Disaster Flood Relief Sluice Gate Actuation | `src/edge/teams/os5_reliable/s4_sluice_gate.py` | |
| OS5-5 | Compound Failure Survivability (WAN Cut + Worker Crash) | `src/edge/teams/os5_reliable/s5_compound_failure.py` | |

## Done vs. still to build
**Done and tested:** bounded queue (drop_oldest), Unix socket framing, SQLite WAL + atomic
event+outbox write, idempotent drain with conservation check, online backup, monotonic-TTL rule
engine, supervisor with crash restart and clean shutdown, /proc metrics, zero-dependency dashboard,
WAN cut/restore end-to-end test, all five theme configs start and run.

**Still to build (the assignment):** the 25 scenario implementations and their tests, the 10-minute
offline demo run, systemd and Docker files (templates provided, **not yet tested**), the report.

## Git workflow
1. `main` always runs: never push broken code to it.
2. One branch per scenario (`os3-s2-priority-queue`), merge via pull request reviewed by someone else.
3. `git pull` from `main` often. Run the tests before every PR.
4. Everyone must be able to explain their own code: 20 points of the grade is an individual oral defense.
