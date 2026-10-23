# Shared runtime crash safety

## Phase 1: durable acceptance and processing

The shared runtime accepts events into `runtime_inbox` in SQLite. The acceptance transaction commits before `SensorGen` proceeds; a repeated `event_id` is ignored by the unique key. The Processor scans pending rows, so rows left by a process crash can be found after restart.

Processing one inbox row is a single SQLite transaction. It records the sensor event, creates its outbox row, stores any rule decisions, and marks the inbox row complete together. A process crash therefore leaves either all of those database effects or none of them. Completed inbox rows are retained, providing acceptance and completion counts and supporting ID consistency checks. Retention means the inbox grows over time; there is no pruning policy or disk-capacity bound, and disk-full or other SQLite write errors can prevent new acceptance.

SQLite is configured for WAL journaling and `synchronous=NORMAL`. This is intended to recover from normal process crashes; it does not claim a power-loss durability guarantee. External physical actuator effects are not covered by the database transaction or an exactly-once guarantee.

Existing storage APIs for standalone scenario code remain available, including direct event-plus-outbox insertion, outbox draining, decisions, health, key/value state, and online backup. These paths are separate from shared-runtime inbox acceptance.

## Phase 2: runtime topology and shutdown

The shared runtime handoff uses only the SQLite `runtime_inbox`; it does not place events on the in-memory `BoundedQueue`. That bounded queue remains available to standalone scenario demonstrations. The `ipc.queue_maxsize` configuration value is accepted but unused by the shared runtime.

The Processor reads up to 50 pending rows per batch and waits 0.05 seconds when idle. During shutdown, the supervisor stops and joins SensorGen first, then signals the other workers. The Processor drains available inbox work, with a three-second drain deadline, and the supervisor joins workers with bounded waits before terminating any that remain alive.

`GET /api/status` reports `ingestion` with `accepted`, `pending`, `completed`, and `consistent`. `accepted` counts all retained inbox rows; `pending` and `completed` count rows by `done`; `consistent` checks inbox/event/outbox relationships, sink delivery relationships, and decision references in one SQLite snapshot. The same status object retains `outbox_pending`, event `counts`, `conservation`, WAN state, and process health.

## Phase 3: validation evidence and remaining checks

**Windows validation:** using Python 3.14.5 and PyYAML 6.0.3, the command `PYTHONPATH=src python -m unittest tests.test_core.TestStorage tests.test_core.TestDecision tests.test_configs tests.test_durable_inbox tests.test_pipeline -v` ran 22 tests in 4.749 seconds: 20 passed and 2 Linux integration tests were skipped. Abrupt-process-kill cases ran on Windows using `Process.kill`, and recovery used a spawned `Storage` helper. Those results validate the database recovery cases on Windows; despite the test name, they do not prove Linux `SIGKILL` behavior or execution of the Linux `processor_main` path. `compileall` for `src` and `tests` and all four configuration tests also passed earlier.

**Supplemental Windows primitive checks:** `PYTHONPATH=src python -m unittest tests.test_core.TestBoundedQueue tests.test_core.TestStopFlag.test_set_wait_is_set tests.test_core.TestUnixSocket -v` produced 2 passes and 1 error because this Windows interpreter does not provide `socket.AF_UNIX`. This is a platform limitation of the test environment, not a shared-runtime IPC source change. Across the focused and supplemental commands, the recorded results are 22 passes, 2 Linux-only skips, and 1 platform error.

**Still pending:** Linux validation, including actual supervised worker restart and WAN integration. On Linux, run the focused command above and the full regression commands `PYTHONPATH=src python -m unittest discover -s tests -v` and `PYTHONPATH=src python scripts/run_all_scenarios.py`. No result from those Linux commands is claimed here.

## Phase 4: reproducible Linux verification

`scripts/verify_linux.py` automates the complete unit-test suite and all scenario runs, and keeps logs and JSON summaries for each run. It requires Linux with `/proc` mounted and Python 3.12 or newer; it refuses unsupported environments before creating artifacts or running tests. It installs no dependencies itself, so install the repository requirements first.

From the repository root on Linux or WSL2:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
PYTHONPATH=src python -m unittest tests.test_verification -v  # optional portable verifier checks
python scripts/verify_linux.py
```

The verifier creates a unique directory under `data/verification/` by default. To select a location, pass `--output PATH`; the path must not already exist, so each run preserves its own artifacts. Each test and scenario stage has a 900-second default timeout, configurable with `--timeout SECONDS`. The run fails for a failed, skipped, or empty unit-test suite, or unless exactly 25 scenario modules are found. Stage logs are `unittest.log` and `scenarios.log`; `unittest-result.json` records test counts and `summary.json` records stage status and environment/git metadata. The `.gitignore` excludes generated verification artifacts.

GitHub Actions runs the verifier on pushes, pull requests, and manual dispatch using Ubuntu 24.04 and Python 3.12. It has read-only repository contents permission, a 35-minute job limit, and uploads the `data/verification/ci` artifacts even when verification fails, with 14-day retention. The local workflow definition was parsed, but no remote workflow run or push occurred in this session.

**Phase 4 validation status:** `PYTHONPATH=src python -m unittest tests.test_verification -v` passed all 7 portable verifier tests in 0.011 seconds. `compileall` for `scripts/verify_linux.py` and `tests/test_verification.py` passed. Invoking the verifier on Windows correctly returned status 2 for the Linux-only requirement without running the suite. These checks cover verifier behavior; they are not Linux runtime validation. Linux full-suite, supervised-restart, WAN, and all-scenario results remain pending until the verifier is run on Linux or through the workflow.
