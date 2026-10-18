"""OS1-2: Competing Occupancy Writers & Race Condition Demonstration.

The unsafe version deliberately makes all workers read the same old value before
writing. The safe version protects the read-modify-write operation with a Mutex
(threading.Lock), so all increments are preserved.
"""
import sys
import threading


def run(workers=80):
    """Return (ok, report_lines) for a deterministic lost-update demonstration."""
    if workers < 2:
        raise ValueError("workers must be at least 2 to demonstrate competing writers")

    # Unsafe: force a race window with a barrier after every worker reads the value.
    unsafe = {"value": 0}
    barrier = threading.Barrier(workers)

    def unsafe_increment():
        old_value = unsafe["value"]
        barrier.wait()
        unsafe["value"] = old_value + 1

    threads = [threading.Thread(target=unsafe_increment) for _ in range(workers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    unsafe_result = unsafe["value"]

    # Safe: lock covers the complete read-modify-write operation.
    safe = {"value": 0}
    mutex = threading.Lock()

    def safe_increment():
        with mutex:
            safe["value"] += 1

    threads = [threading.Thread(target=safe_increment) for _ in range(workers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    safe_result = safe["value"]

    ok = unsafe_result < workers and safe_result == workers
    return ok, [
        f"concurrent writers: {workers}; expected final counter: {workers}",
        f"without Mutex: {unsafe_result} (lost {workers - unsafe_result} update(s))",
        f"with Mutex: {safe_result} (lost 0 updates)",
        "Mutex protects the entire read-modify-write operation, not just one line",
    ]


def main():
    ok, lines = run()
    print(f"[{'PASS' if ok else 'FAIL'}] OS1-2 Competing occupancy writers & race condition")
    for line in lines:
        print("      ", line)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
