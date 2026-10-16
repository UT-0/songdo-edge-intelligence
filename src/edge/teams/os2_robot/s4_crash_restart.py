"""OS2-4: Worker Crash & Supervised Automatic Restart

Mission : Inject SIGKILL into the motion worker and verify bounded recovery.
Concept : Supervisor traps SIGCHLD, restarts the failed child within 2.0 s, and restores state.

Owner   : (write names here)
Test    : tests/os2/test_s4_crash_restart.py  (create it)
Run     : bash scripts/start_demo.sh OS2

Only edit THIS file, its test, and its report section. Need a change in
src/edge/core/ or sql/schema.sql? Ask the core owners.
"""

# TODO: implement OS2-4
