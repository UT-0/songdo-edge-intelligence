# Songdo Edge Intelligence (OS course project)

A multi-process Linux edge node that keeps working when the WAN is cut, then drains its
durable outbox with zero lost events. Python 3.12 + SQLite (WAL) + standard library only
(plus `pyyaml`).

## Quickstart
```bash
bash scripts/preflight.sh        # check the machine
bash scripts/setup.sh            # .venv + dependencies + database
PYTHONPATH=src python -m unittest discover -s tests -v    # run tests (uses .venv python if you prefer)
bash scripts/start_demo.sh       # start the node, open http://127.0.0.1:8000
```
In the dashboard: **Simulate WAN Internet Cut** -> events keep arriving, *Outbox queued* grows.
**Restore WAN Connection** -> the backlog drains, *Conserved* stays `yes`.

## How it works
```
SensorGen --(BoundedQueue, 500, drop_oldest)--> Processor --> SQLite (events, decisions, outbox)
                                                                   |
HealthMon (/proc -> process_health)      SyncWorker (drains outbox only while WAN online)
API (http.server dashboard + /api/status, /api/wan/cut, /api/wan/restore)
Supervisor starts, monitors, restarts and cleanly stops all of the above.
```

## Repo layout and ownership
| Path | What | Who edits |
|---|---|---|
| `src/edge/core/` (`models`, `ipc`, `storage`, `procfs`, `config`) | shared core | **Core owners only** (others: open a PR) |
| `src/edge/supervisor.py`, `workers.py`, `sync_worker.py`, `decision.py`, `api_server.py` | pipeline | Core owners; scenario teams extend via their own files |
| `src/edge/scenarios/sN_*.py` | one file per scenario | **That scenario's mini team** |
| `tests/` | `test_core.py`, `test_pipeline.py` + one test per scenario | scenario teams add `test_sN_*.py` |
| `config/node.yaml`, `sql/schema.sql` | shared settings and tables | small changes only, announce in the group chat |
| `scripts/`, `systemd/`, `container/` | ops | Ops owner |

### Scenario owners (fill in)
| Scenario | File | Mini team |
|---|---|---|
| 1 ingestion | `s1_ingestion.py` | |
| 2 concurrency | `s2_concurrency.py` | |
| 3 decisions | `s3_decision.py` | |
| 4 supervision/ops | `s4_supervision.py` | |
| 5 offline | `s5_offline.py` | |

*(Scenario numbering differs per team theme in the handbook: rename the files to match yours.)*

## What is already done vs. still to build
**Done and tested:** bounded queue (drop_oldest), Unix socket framing, SQLite WAL + atomic
event+outbox write, idempotent drain with conservation check, online backup + integrity check,
monotonic-TTL rule engine, supervisor with crash restart and clean shutdown, `/proc` health
metrics, zero-dependency dashboard, WAN cut/restore end-to-end test.

**Still to build (the actual assignment):** your theme's real sensors and rules in `node.yaml` and
the scenario files; the race-condition and deadlock demos; priority queue / event-time handling /
other theme-specific scenarios; Unix socket wired into the pipeline; the 10-minute offline demo run;
systemd and Docker files (templates provided, **not yet tested**); report.

## Git workflow
1. `main` always runs: never push broken code to it.
2. One branch per scenario (`s3-decision`), merge into `main` through a pull request reviewed by someone else.
3. `git pull` from `main` often. Run the tests before every PR.
4. Everyone must be able to explain their own code: 20 points of the grade is an individual oral defense.
