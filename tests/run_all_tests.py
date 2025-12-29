#!/usr/bin/env python3
"""
Unified test runner for lldb-objc project.

This script runs all implemented feature tests and provides a summary
in pytest-style output format for suites of test suites.

Usage:
    ./tests/run_all_tests.py              # Run all implemented feature tests
    ./tests/run_all_tests.py --all        # Include future feature tests
    ./tests/run_all_tests.py --quick      # Run quick tests only (skip slow ones)
    ./tests/run_all_tests.py --verbose    # Show detailed output from each suite
    ./tests/run_all_tests.py obrk ocls    # Run specific test suites
"""

import subprocess
import sys
import os
import time
import argparse
import re

# Get the script directory and project root
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..'))

# Test suites for implemented features
IMPLEMENTED_TESTS = [
    ('obrk', 'test_obrk.py', 'Objective-C breakpoint command'),
    ('ocls', 'test_ocls.py', 'Objective-C class finder'),
    ('osel', 'test_osel.py', 'Objective-C selector finder'),
    ('ocall', 'test_ocall.py', 'Objective-C method caller'),
    ('owatch', 'test_owatch.py', 'Objective-C method watcher'),
    ('oprotos', 'test_oprotos.py', 'Objective-C protocol conformance'),
    ('hierarchy', 'test_hierarchy.py', 'Class hierarchy display'),
    ('ivars_props', 'test_ivars_props.py', 'Instance variables and properties'),
    ('osel_perf', 'test_osel_perf.py', 'osel performance optimization'),
]

# Quick tests (subset of implemented tests that run fast)
QUICK_TESTS = [
    ('obrk', 'test_obrk.py', 'Objective-C breakpoint command'),
    ('hierarchy', 'test_hierarchy.py', 'Class hierarchy display'),
    ('ivars_props', 'test_ivars_props.py', 'Instance variables and properties'),
]

# Tests for future/unimplemented features (in tests/future/ directory)
FUTURE_TESTS = [
    # All features now implemented and moved to IMPLEMENTED_TESTS
]

# Performance/timing tests (optional)
PERF_TESTS = [
    ('timing', 'test_timing.py', 'Detailed timing measurements'),
]


def check_binary():
    """Check if HelloWorld binary exists."""
    hello_world_path = os.path.join(PROJECT_ROOT, 'examples/HelloWorld/HelloWorld/HelloWorld')
    if not os.path.exists(hello_world_path):
        print("=" * 70)
        print("SETUP ERROR")
        print("=" * 70)
        print(f"\nHelloWorld binary not found!")
        print(f"  Expected: {hello_world_path}")
        print(f"  Build with: cd examples/HelloWorld && xcodebuild\n")
        return False
    return True


def run_test_suite(test_file, verbose=False):
    """
    Run a single test suite and return results.

    Returns:
        Tuple of (passed, total, elapsed_time, output, suite_failures)
        where suite_failures is a list of detailed failure information
    """
    test_path = os.path.join(SCRIPT_DIR, test_file)

    if not os.path.exists(test_path):
        return None, None, 0, f"Test file not found: {test_file}", []

    start_time = time.time()

    try:
        result = subprocess.run(
            [sys.executable, test_path],
            capture_output=True,
            text=True,
            timeout=300,  # 5 minute timeout per suite
            cwd=PROJECT_ROOT
        )
        elapsed = time.time() - start_time
        output = result.stdout + result.stderr

        # Parse results from output
        # Look for pytest-style summary: "N passed in X.XXs" or "N failed, M passed in X.XXs"
        passed = 0
        total = 0

        # Try to parse from summary line
        summary_match = re.search(r'(\d+)\s+passed\s+in\s+[\d.]+s', output)
        failed_match = re.search(r'(\d+)\s+failed(?:,\s+(\d+)\s+passed)?\s+in\s+[\d.]+s', output)

        if failed_match:
            failed = int(failed_match.group(1))
            passed = int(failed_match.group(2)) if failed_match.group(2) else 0
            total = failed + passed
        elif summary_match:
            passed = int(summary_match.group(1))
            total = passed
        else:
            # Fallback: count dots and F's from progress line
            progress_match = re.search(r'([.F]+)\s+\[\s*\d+%\]', output)
            if progress_match:
                progress = progress_match.group(1)
                passed = progress.count('.')
                total = len(progress)

        # Extract failure details if present
        failures = []
        if total > passed:  # There are failures
            # Extract the FAILURES section
            failures_section = re.search(
                r'={70}\nFAILURES\n={70}(.*?)(?:={70}|\Z)',
                output,
                re.DOTALL
            )
            if failures_section:
                # Split by test separator lines
                test_failures = re.split(r'_{70}\n', failures_section.group(1))
                for failure in test_failures:
                    failure = failure.strip()
                    if failure:
                        # Extract test name (first line) and details
                        lines = failure.split('\n', 1)
                        if len(lines) >= 2:
                            test_name = lines[0].strip()
                            details = lines[1].strip()
                            failures.append({'name': test_name, 'details': details})
                        elif lines:
                            failures.append({'name': lines[0].strip(), 'details': ''})

        return passed, total, elapsed, output, failures

    except subprocess.TimeoutExpired:
        elapsed = time.time() - start_time
        return 0, 1, elapsed, "TIMEOUT: Test suite exceeded 5 minute limit", [
            {'name': 'TIMEOUT', 'details': 'Test suite exceeded 5 minute limit'}
        ]
    except Exception as e:
        elapsed = time.time() - start_time
        return 0, 1, elapsed, f"ERROR: {str(e)}", [
            {'name': 'ERROR', 'details': str(e)}
        ]


def main():
    parser = argparse.ArgumentParser(description='Run lldb-objc test suites')
    parser.add_argument('--all', action='store_true',
                        help='Include future/unimplemented feature tests')
    parser.add_argument('--quick', action='store_true',
                        help='Run quick tests only')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='Show detailed output from each test suite')
    parser.add_argument('--perf', action='store_true',
                        help='Include performance tests')
    parser.add_argument('suites', nargs='*',
                        help='Specific test suites to run (e.g., obrk ocls)')

    args = parser.parse_args()

    # Check for HelloWorld binary
    if not check_binary():
        sys.exit(1)

    # Determine which tests to run
    if args.suites:
        # Run specific suites
        all_tests = IMPLEMENTED_TESTS + FUTURE_TESTS + PERF_TESTS
        tests_to_run = [(name, file, desc) for name, file, desc in all_tests
                        if name in args.suites]
        if not tests_to_run:
            print(f"\nNo matching test suites: {args.suites}")
            print(f"Available suites: {', '.join([t[0] for t in IMPLEMENTED_TESTS + FUTURE_TESTS + PERF_TESTS])}\n")
            sys.exit(1)
    elif args.quick:
        tests_to_run = QUICK_TESTS
    elif args.all:
        tests_to_run = IMPLEMENTED_TESTS + FUTURE_TESTS
    else:
        tests_to_run = IMPLEMENTED_TESTS

    if args.perf and not args.suites:
        tests_to_run = tests_to_run + PERF_TESTS

    # Print pytest-style header
    print("=" * 70)
    print("test session starts")
    print(f"platform darwin -- Python {'.'.join(map(str, sys.version_info[:3]))}")
    print(f"collected {len(tests_to_run)} test suites\n")

    # Run each test suite
    suite_results = []
    total_passed = 0
    total_tests = 0
    total_time = 0
    failed_suites = []

    overall_start = time.time()

    for idx, (suite_name, test_file, description) in enumerate(tests_to_run, 1):
        if args.verbose:
            # In verbose mode, show the suite name and let it print its output
            print(f"\n{'=' * 70}")
            print(f"{suite_name} :: {description}")
            print("=" * 70)

        passed, total, elapsed, output, failures = run_test_suite(test_file, args.verbose)

        if passed is None:
            # Skipped test
            if args.verbose:
                print(f"\nSKIPPED: {output}")
            else:
                print("s", end="", flush=True)
            suite_results.append({
                'name': suite_name,
                'status': 'SKIPPED',
                'passed': 0,
                'total': 0,
                'elapsed': elapsed,
                'failures': []
            })
        else:
            if args.verbose:
                # Print the actual suite output
                print(output)
            else:
                # Pytest-style progress indicator
                if passed == total and total > 0:
                    print(".", end="", flush=True)
                else:
                    print("F", end="", flush=True)
                    failed_suites.append({
                        'name': suite_name,
                        'description': description,
                        'passed': passed,
                        'total': total,
                        'elapsed': elapsed,
                        'failures': failures,
                        'output': output
                    })

            suite_results.append({
                'name': suite_name,
                'status': 'PASS' if passed == total and total > 0 else 'FAIL',
                'passed': passed,
                'total': total,
                'elapsed': elapsed,
                'failures': failures
            })

            total_passed += passed
            total_tests += total
            total_time += elapsed

        # Line break every 60 suites or at end
        if not args.verbose and (idx % 60 == 0 or idx == len(tests_to_run)):
            percentage = int(100 * idx / len(tests_to_run))
            print(f" [{percentage:3d}%]")

    overall_elapsed = time.time() - overall_start

    # Print failures section (pytest style) - only if not in verbose mode
    if not args.verbose and failed_suites:
        print(f"\n{'=' * 70}")
        print("FAILURES")
        print("=" * 70)

        for suite in failed_suites:
            print(f"\n{'_' * 70}")
            print(f"{suite['name']} :: {suite['description']}")
            print(f"Result: {suite['passed']}/{suite['total']} passed ({suite['elapsed']:.2f}s)")
            print("_" * 70)

            if suite['failures']:
                for failure in suite['failures'][:5]:  # Show first 5 failures
                    print(f"\n  {failure['name']}")
                    # Show first 300 chars of details
                    details = failure['details'][:300]
                    if details:
                        # Indent the details
                        for line in details.split('\n'):
                            if line.strip():
                                print(f"    {line}")
                    if len(failure['details']) > 300:
                        print(f"    ... ({len(failure['details']) - 300} more characters)")

                if len(suite['failures']) > 5:
                    print(f"\n  ... and {len(suite['failures']) - 5} more failures")

            # Show how to re-run this specific suite
            print(f"\n  Re-run this suite: ./tests/{suite['name'] if suite['name'].startswith('test_') else 'test_' + suite['name'] + '.py'}")
            if not suite['name'].startswith('test_'):
                print(f"  Re-run this suite: python3 tests/test_{suite['name']}.py")

    # Print summary section (pytest style)
    print(f"\n{'=' * 70}")

    suites_passed = sum(1 for r in suite_results if r['status'] == 'PASS')
    suites_failed = sum(1 for r in suite_results if r['status'] == 'FAIL')
    suites_skipped = sum(1 for r in suite_results if r['status'] == 'SKIPPED')

    if not args.verbose:
        # Show suite-level summary
        summary_parts = []
        if suites_failed > 0:
            summary_parts.append(f"\033[91m{suites_failed} failed\033[0m")
        if suites_passed > 0:
            summary_parts.append(f"\033[92m{suites_passed} passed\033[0m")
        if suites_skipped > 0:
            summary_parts.append(f"{suites_skipped} skipped")

        print(f"{', '.join(summary_parts)} in {overall_elapsed:.2f}s")

        # Show test-level summary underneath
        if total_tests > 0:
            test_summary_parts = []
            failed_tests = total_tests - total_passed
            if failed_tests > 0:
                test_summary_parts.append(f"{failed_tests} failed")
            if total_passed > 0:
                test_summary_parts.append(f"{total_passed} passed")
            print(f"({', '.join(test_summary_parts)} tests total)")
    else:
        # In verbose mode, just show overall summary
        if suites_failed == 0:
            print(f"\033[92mAll {suites_passed} suites passed\033[0m ({total_passed} tests) in {overall_elapsed:.2f}s")
        else:
            print(f"\033[91m{suites_failed} of {len(suite_results)} suites failed\033[0m in {overall_elapsed:.2f}s")

    print("=" * 70)

    # Exit with appropriate code
    sys.exit(0 if suites_failed == 0 else 1)


if __name__ == '__main__':
    main()
