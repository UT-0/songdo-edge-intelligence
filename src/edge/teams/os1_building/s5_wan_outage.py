"""OS1-5: Signature WAN Outage & Offline Outbox Queueing

Mission : Simulate a WAN drop and verify zero data loss.
Concept : DEMO: disconnect mock WAN upstream for 10 minutes, watch events accumulate in the durable outbox, reconnect and verify complete batch drainage without duplicate entries.

Owner   : (write names here)
Test    : tests/os1/test_s5_wan_outage.py  (create it)
Run     : bash scripts/start_demo.sh OS1

Only edit THIS file, its test, and its report section. Need a change in
src/edge/core/ or sql/schema.sql? Ask the core owners.
"""

# TODO: implement OS1-5
