#!/usr/bin/env python3
"""
Master test runner that runs all test suites with a single shared LLDB session.

This dramatically improves performance by avoiding the overhead of starting
a new LLDB process for each test file (typically 4-6s per spawn).

Timing information is logged to tests/.test_timings.log (gitignored) in a
human-readable format with details by suite and individual test case.
The log file is cleared on each run.
"""

import sys
import os
import importlib.util
import time
from datetime import datetime

# Add tests directory to path for imports
TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(TESTS_DIR)
sys.path.insert(0, TESTS_DIR)

from test_helpers import (
    SharedLLDBSession,
    run_shared_test_suite,
    check_hello_world_binary,
)

# Test files to run (in order)
TEST_FILES = [
    "test_obrk.py",
    "test_ocls.py",
    "test_osel.py",
    "test_ocall.py",
    "test_owatch.py",
    "test_opool.py",
    "test_oinstance.py",
    "test_odump.py",
    "test_oentitlements.py",
    "test_okeychain.py",
    "test_hierarchy.py",
    "test_ivars_props.py",
    "test_timing.py",
    "test_osel_perf.py",
]


def load_test_module(test_file):
    """Load a test module by file path."""
    module_name = test_file.replace(".py", "")
    file_path = os.path.join(TESTS_DIR, test_file)

    spec = importlib.util.spec_from_file_location(module_name, file_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load test file: {test_file}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def collect_all_scripts():
    """
    Collect all unique scripts needed by all test files.

    Since we load all scripts once, we take the union of all requirements.
    Scripts that use "scripts" or "scripts/" load the entire package.
    """
    # Just load the entire scripts directory to support all tests
    return ["scripts"]


def init_timing_log(log_file, run_timestamp):
    """Initialize timing log file (clear if exists) with header."""
    with open(log_file, "w") as f:
        f.write("=" * 80 + "\n")
        f.write("TEST TIMING REPORT\n")
        f.write("=" * 80 + "\n")
        f.write(f"Run timestamp: {run_timestamp}\n")
        f.write(f"Platform: darwin -- Python {'.'.join(map(str, sys.version_info[:3]))}\n")
        f.write("\n")


def log_suite_timing(log_file, suite_data):
    """Log timing data for a test suite in human-readable format."""
    with open(log_file, "a") as f:
        f.write("-" * 80 + "\n")
        f.write(f"Suite: {suite_data['suite']}\n")
        f.write("-" * 80 + "\n")
        f.write(f"  Status:   {suite_data['passed']}/{suite_data['total']} passed")
        if suite_data['failed'] > 0:
            f.write(f", {suite_data['failed']} FAILED")
        f.write("\n")
        f.write(f"  Time:     {suite_data['elapsed']:.3f}s\n")
        f.write(f"  Avg/test: {suite_data['elapsed'] / suite_data['total']:.3f}s\n")
        f.write("\n")
        f.write("  Test Cases:\n")

        for test in suite_data['tests']:
            status = "✓" if test['passed'] else "✗"
            # Clean up test name (remove suite prefix)
            name = test['name'].split("::", 1)[1] if "::" in test['name'] else test['name']
            f.write(f"    {status} {name:<60} {test['time']:>8.3f}s\n")

        f.write("\n")


def log_summary(log_file, summary_data):
    """Log overall test run summary."""
    with open(log_file, "a") as f:
        f.write("=" * 80 + "\n")
        f.write("SUMMARY\n")
        f.write("=" * 80 + "\n")
        f.write(f"  Total tests:      {summary_data['total_tests']}\n")
        f.write(f"  Passed:           {summary_data['passed']}\n")
        f.write(f"  Failed:           {summary_data['failed']}\n")
        f.write(f"  Suites run:       {summary_data['suites_run']}\n")
        f.write("\n")
        f.write(f"  Session startup:  {summary_data['session_startup']:.3f}s\n")
        f.write(f"  Total time:       {summary_data['total_elapsed']:.3f}s\n")
        if summary_data['total_tests'] > 0:
            avg = summary_data['total_elapsed'] / summary_data['total_tests']
            f.write(f"  Avg per test:     {avg:.3f}s\n")
        f.write("\n")
        f.write("=" * 80 + "\n")


def main():
    """Run all test suites with a single shared LLDB session."""
    if not check_hello_world_binary():
        sys.exit(1)

    # Set up timing log
    log_file = os.path.join(TESTS_DIR, ".test_timings.log")

    # Start timing
    total_start_time = time.time()
    run_timestamp = datetime.now().isoformat()

    # Initialize timing log (clears previous data)
    init_timing_log(log_file, run_timestamp)

    # Print header
    print("=" * 70)
    print("MASTER TEST RUNNER - All suites with shared LLDB session")
    print("=" * 70)
    print(f"Timestamp: {run_timestamp}")
    print(f"Platform: darwin -- Python {'.'.join(map(str, sys.version_info[:3]))}")
    print(f"Test files: {len(TEST_FILES)}")
    print(f"Timing log: {log_file}")
    print()

    # Collect all scripts
    scripts = collect_all_scripts()
    print(f"Loading scripts: {scripts}")
    print()

    # Track overall results
    all_suite_results = []
    total_tests_passed = 0
    total_tests_run = 0
    total_tests_failed = 0

    # Create single shared session for all test suites
    session_start_time = time.time()
    print("Starting shared LLDB session...")

    try:
        with SharedLLDBSession(scripts=scripts) as session:
            session_startup_time = time.time() - session_start_time
            print(f"Session started in {session_startup_time:.2f}s\n")

            # Run each test suite
            for i, test_file in enumerate(TEST_FILES, 1):
                suite_name = test_file.replace("test_", "").replace(".py", "")
                print(f"[{i}/{len(TEST_FILES)}] Running {test_file}...")

                try:
                    # Load test module
                    module = load_test_module(test_file)

                    # Get test specs
                    if not hasattr(module, "get_test_specs"):
                        print(f"  ⚠️  Skipping {test_file}: no get_test_specs() function")
                        continue

                    test_specs = module.get_test_specs()

                    # Run tests with shared session
                    suite_start = time.time()
                    passed, total, elapsed, results = run_shared_test_suite(
                        name=f"{suite_name.upper()} TEST SUITE",
                        test_specs=test_specs,
                        session=session,  # Use shared session
                        suite_prefix=f"{test_file}::",
                    )
                    suite_end = time.time()

                    # Track results
                    failed = total - passed
                    total_tests_passed += passed
                    total_tests_run += total
                    total_tests_failed += failed

                    # Print suite summary
                    if failed == 0:
                        print(f"  ✅ {passed}/{total} passed in {elapsed:.2f}s")
                    else:
                        print(f"  ❌ {passed}/{total} passed, {failed} failed in {elapsed:.2f}s")

                    # Log timing data
                    suite_data = {
                        "timestamp": run_timestamp,
                        "suite": test_file,
                        "passed": passed,
                        "total": total,
                        "failed": failed,
                        "elapsed": elapsed,
                        "tests": [
                            {
                                "name": r.name,
                                "passed": r.passed,
                                "time": r.execution_time,
                            }
                            for r in results
                        ],
                    }
                    all_suite_results.append(suite_data)
                    log_suite_timing(log_file, suite_data)

                except Exception as e:
                    print(f"  ⚠️  Error running {test_file}: {e}")
                    import traceback

                    traceback.print_exc()

                print()

    except Exception as e:
        print(f"Fatal error with shared session: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)

    # Calculate total time
    total_elapsed = time.time() - total_start_time

    # Print overall summary
    print("=" * 70)
    print("MASTER TEST RUNNER SUMMARY")
    print("=" * 70)
    print(f"Total tests run:    {total_tests_run}")
    print(f"Total passed:       {total_tests_passed}")
    print(f"Total failed:       {total_tests_failed}")
    print(f"Session startup:    {session_startup_time:.2f}s")
    print(f"Total time:         {total_elapsed:.2f}s")
    print(f"Avg per test:       {total_elapsed/total_tests_run:.3f}s" if total_tests_run > 0 else "")
    print()

    # Log overall summary
    summary_data = {
        "timestamp": run_timestamp,
        "suite": "__SUMMARY__",
        "total_tests": total_tests_run,
        "passed": total_tests_passed,
        "failed": total_tests_failed,
        "session_startup": session_startup_time,
        "total_elapsed": total_elapsed,
        "suites_run": len(all_suite_results),
    }
    log_summary(log_file, summary_data)

    if total_tests_failed == 0:
        print(f"\033[92m✅ All {total_tests_passed} tests passed!\033[0m")
        print("=" * 70)
        sys.exit(0)
    else:
        print(f"\033[91m❌ {total_tests_failed} tests failed\033[0m")
        print("=" * 70)
        sys.exit(1)


if __name__ == "__main__":
    main()
