"""OS1-2: Competing Occupancy Writers & Race Condition Demonstration

Mission : Prove and prevent race conditions during concurrent turnstile counts.
Concept : Show counter corruption under preemption, then fix with a Mutex. TEST: 80 concurrent increments; unprotected counter < 80, mutex counter == 80.

Owner   : (write names here)
Test    : tests/os1/test_s2_race_condition.py  (create it)
Run     : bash scripts/start_demo.sh OS1

Only edit THIS file, its test, and its report section. Need a change in
src/edge/core/ or sql/schema.sql? Ask the core owners.
"""

# TODO: implement OS1-2
