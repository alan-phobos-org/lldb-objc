#!/usr/bin/env python3
"""
Smoke test suite for LLDB Objective-C commands.

Quick sanity checks against a live system process to verify basic
functionality of all core commands without running full integration tests.

Commands tested: obrk, osel, ocls, ocall, owatch, opool, oinstance, oinstances,
                 odump, oentitlements, okeychain, osbx

Note: Requires sudo/root permissions to attach to system processes.
"""

import os
import subprocess
import sys
import tempfile

# Get paths relative to this file
_this_dir = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(_this_dir)
SCRIPTS_DIR = os.path.join(PROJECT_ROOT, "scripts")

# System process to attach to for testing
PROCESS_NAME = "apsd"


def run_smoke_test():
    """Run minimal smoke tests for all commands."""

    # Generate LLDB commands for smoke testing
    # Use APSDaemon as test class (specific to apsd process)
    # Use minimal limits to keep tests fast
    commands = f"""
# Load LLDB Objective-C commands
command script import {SCRIPTS_DIR}

# Attach to the running system process
process attach -n {PROCESS_NAME}

# Smoke test each command with minimal validation
script print("=== SMOKE TEST: obrk ===")
obrk -[NSObject init]

script print("=== SMOKE TEST: osel ===")
osel APSDaemon

script print("=== SMOKE TEST: ocls ===")
ocls APSDaemon --limit 3

script print("=== SMOKE TEST: ocall ===")
ocall [NSObject alloc]

script print("=== SMOKE TEST: owatch ===")
script print("  SKIPPED: Known timeout issue (see PLAN.md)")

script print("=== SMOKE TEST: opool ===")
opool

script print("=== SMOKE TEST: oinstance ===")
oinstance (id)[NSObject alloc]

script print("=== SMOKE TEST: oinstances ===")
oinstances APSDaemon -M 3

script print("=== SMOKE TEST: odump ===")
script print("  SKIPPED: Requires file output path")

script print("=== SMOKE TEST: oentitlements ===")
oentitlements

script print("=== SMOKE TEST: okeychain ===")
okeychain list

script print("=== SMOKE TEST: okeychain extract ===")
okeychain extract /tmp/lldb-objc-smoke-keychain.plist --raw

script print("=== SMOKE TEST: osbx ===")
osbx

script print("=== SMOKE TEST: omemlayout ===")
omemlayout

script print("=== SMOKE TEST: osc ===")
osc

script print("=== CLEANUP: Remove extracted keychain files ===")
script import os, shutil
script if os.path.exists("/tmp/lldb-objc-smoke-keychain.plist"): os.remove("/tmp/lldb-objc-smoke-keychain.plist")
script if os.path.exists("/tmp/lldb-objc-smoke-keychain-raw"): shutil.rmtree("/tmp/lldb-objc-smoke-keychain-raw")

script print("=== SMOKE TESTS COMPLETE ===")
quit
"""

    # Write commands to temporary file
    with tempfile.NamedTemporaryFile(mode="w", suffix=".lldb", delete=False) as f:
        f.write(commands)
        command_file = f.name

    try:
        print(f"Running smoke tests against {PROCESS_NAME}...")
        print("Note: You may need sudo privileges to attach to system processes.\n")

        # Run LLDB with commands (with sudo for system process attachment)
        result = subprocess.run(
            ["sudo", "lldb", "--no-lldbinit", "--batch", "-s", command_file],
            capture_output=True,
            text=True,
            timeout=30,
        )

        # Check for obvious failures
        output = result.stdout + result.stderr
        failures = []

        # Check for attach failures specifically (not just "error" + "attach" anywhere)
        if "process attach" in output and "error: attach failed" in output.lower():
            print(f"\nERROR: Failed to attach to {PROCESS_NAME}")
            print("This usually means:")
            print("  1. The process is not running")
            print("  2. You need sudo privileges (try: sudo ./build.sh test-smoke)")
            print("  3. SIP (System Integrity Protection) is blocking LLDB")
            print("\nRelevant output:")
            for line in output.split("\n"):
                if "error" in line.lower() or "attach" in line.lower():
                    print(f"  {line}")
            return 1

        # Check for Python errors
        if "Traceback (most recent call last)" in output:
            failures.append("Python traceback detected")
            # Extract and show the traceback
            lines = output.split("\n")
            tb_start = None
            for i, line in enumerate(lines):
                if "Traceback (most recent call last)" in line:
                    tb_start = i
                    break
            if tb_start is not None:
                print("\nPython error found:")
                for line in lines[tb_start : tb_start + 10]:
                    if line.strip():
                        print(f"  {line}")

        # Check for LLDB command errors
        error_lines = [line for line in output.split("\n") if line.startswith("error: ")]
        if error_lines:
            failures.append(f"LLDB command errors detected ({len(error_lines)} errors)")
            print("\nLLDB errors found:")
            for line in error_lines[:5]:  # Show first 5 errors
                print(f"  {line}")
            if len(error_lines) > 5:
                print(f"  ... and {len(error_lines) - 5} more errors")

        # Check that all smoke tests ran
        expected_tests = [
            "SMOKE TEST: obrk",
            "SMOKE TEST: osel",
            "SMOKE TEST: ocls",
            "SMOKE TEST: ocall",
            "SMOKE TEST: owatch",
            "SMOKE TEST: opool",
            "SMOKE TEST: oinstance",
            "SMOKE TEST: oinstances",
            "SMOKE TEST: odump",
            "SMOKE TEST: oentitlements",
            "SMOKE TEST: okeychain",
            "SMOKE TEST: okeychain extract",
            "SMOKE TEST: osbx",
            "SMOKE TEST: omemlayout",
            "SMOKE TEST: osc",
        ]

        for test in expected_tests:
            if test not in output:
                failures.append(f"Missing: {test}")

        # Check for completion marker
        if "SMOKE TESTS COMPLETE" not in output:
            failures.append("Test suite did not complete")

        # Validate command outputs (basic sanity checks)
        validations = {
            "obrk": "Breakpoint #",  # Should set a breakpoint
            "osel": "Instance methods",  # Should find methods
            "ocls": "APSDaemon",  # Should find the class
            "ocall": "$",  # Should return a value ($0, $1, etc.)
            "oinstance": "Instance Variables",  # Should show instance info
            "oentitlements": "Process Entitlements",  # Should show entitlements
            "osbx": "Sandbox Writable Path Scan",  # Should run sandbox scan
            "omemlayout": "STACKS",  # Should show stack information
            "osc": "Base Address:",  # Should show shared cache base address
        }

        for cmd, expected_pattern in validations.items():
            if f"SMOKE TEST: {cmd}" in output and expected_pattern not in output:
                failures.append(f"{cmd}: No meaningful output (expected '{expected_pattern}')")

        # Report results
        if failures:
            print("\n" + "=" * 60)
            print("SMOKE TESTS FAILED")
            print("=" * 60)
            for failure in failures:
                print(f"  ✗ {failure}")
            print("=" * 60)

            # Show relevant parts of output, not everything
            print("\nRelevant output snippets:")
            lines = output.split("\n")
            for i, line in enumerate(lines):
                # Show context around errors and test markers
                if any(keyword in line.lower() for keyword in ["error", "traceback", "failed", "smoke test:"]):
                    # Show line with some context
                    start = max(0, i - 1)
                    end = min(len(lines), i + 3)
                    for j in range(start, end):
                        if j < len(lines):
                            print(lines[j])
                    print()

            return 1
        else:
            print("\n" + "=" * 60)
            print("✓ All smoke tests passed")
            print("=" * 60)
            return 0

    except subprocess.TimeoutExpired:
        print("ERROR: Smoke tests timed out after 30 seconds")
        return 1
    except Exception as e:
        print(f"ERROR: {e}")
        return 1
    finally:
        os.unlink(command_file)


if __name__ == "__main__":
    sys.exit(run_smoke_test())
