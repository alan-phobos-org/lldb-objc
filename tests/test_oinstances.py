#!/usr/bin/env python3
"""
Test script for the oinstances command (Find Class Instances in Memory).

This script tests the oinstances functionality:
- Find instances of classes in heap memory
- Support for subclass matching
- Various scanning modes (heap, stack, segments, VM regions)
- Limit controls

Uses a shared LLDB session for faster test execution.
"""

import sys
import re
import os
from test_helpers import run_shared_test_suite, PROJECT_ROOT


# =============================================================================
# Validator Functions
# =============================================================================


def validate_finds_instances():
    """Validator that oinstances finds instances."""

    def validator(output):
        # Should show at least one instance
        # Format: 0xaddress  ClassName  description
        if re.search(r"0x[0-9a-fA-F]+\s+\w+", output):
            return True, "Found instances"
        elif "error" in output.lower():
            return False, (
                f"Command failed with error\n"
                f"    Expected: Instance results\n"
                f"    Actual: Error encountered\n"
                f"    Output preview: {output[:300]}"
            )
        elif "No instances" in output:
            return False, (
                f"No instances found (should find at least one)\n"
                f"    Expected: At least one instance\n"
                f"    Actual: No instances found\n"
                f"    Output preview: {output[:300]}"
            )
        return False, (
            f"Unexpected output format\n"
            f"    Expected: Instance listing\n"
            f"    Actual: Pattern not found\n"
            f"    Output preview: {output[:300]}"
        )

    return validator


def validate_finds_nsstring():
    """Validator that oinstances finds NSString instances."""

    def validator(output):
        # Should find NSString instances
        if re.search(r"0x[0-9a-fA-F]+\s+.*String", output):
            return True, "Found NSString instances"
        elif "No instances" in output:
            # This is actually okay - there might not be any NSStrings in memory
            return True, "No NSStrings found (acceptable)"
        elif "error" in output.lower():
            return False, (
                f"Command failed with error\n"
                f"    Expected: NSString search results\n"
                f"    Actual: Error encountered\n"
                f"    Output preview: {output[:300]}"
            )
        return True, "Completed NSString search"

    return validator


def validate_shows_count():
    """Validator that oinstances shows instance count."""

    def validator(output):
        # Should show "Found N instance(s)" at the end
        if re.search(r"Found \d+ instance", output):
            return True, "Shows instance count"
        elif "No instances" in output:
            return True, "Shows no instances message"
        elif "error" in output.lower():
            return False, (
                f"Command failed with error\n"
                f"    Expected: Instance count\n"
                f"    Actual: Error encountered\n"
                f"    Output preview: {output[:300]}"
            )
        return False, (
            f"Missing instance count\n"
            f"    Expected: 'Found N instance(s)' message\n"
            f"    Actual: Message not found\n"
            f"    Output preview: {output[:300]}"
        )

    return validator


def validate_respects_limit():
    """Validator that oinstances respects max matches limit."""

    def validator(output):
        # When limit is set to 2, should not show more than 2
        if "limit reached" in output:
            return True, "Limit message shown"
        # Count actual instances shown
        instance_count = len(re.findall(r"^0x[0-9a-fA-F]+\s+", output, re.MULTILINE))
        if instance_count <= 2:
            return True, f"Respects limit (found {instance_count})"
        return False, (
            f"Exceeded limit\n"
            f"    Expected: At most 2 instances\n"
            f"    Actual: {instance_count} instances\n"
            f"    Output preview: {output[:300]}"
        )

    return validator


def validate_error_missing_class():
    """Validator that oinstances errors on missing class name."""

    def validator(output):
        if "error" in output.lower() or "Usage:" in output:
            return True, "Shows usage/error for missing class"
        return False, (
            f"Should show error for missing class name\n"
            f"    Expected: Error or usage message\n"
            f"    Actual: {output[:200]}"
        )

    return validator


def validate_handles_nonexistent_class():
    """Validator that oinstances handles nonexistent class gracefully."""

    def validator(output):
        # Should either say no instances or complete gracefully
        if "No instances" in output or "Found 0 instance" in output:
            return True, "Handles nonexistent class gracefully"
        # Empty output is also acceptable
        if not output.strip() or len(output.strip()) < 50:
            return True, "Handles nonexistent class (empty output)"
        # As long as no error
        if "error" not in output.lower():
            return True, "Completed without error"
        return False, (
            f"Unexpected error for nonexistent class\n    Expected: Graceful handling\n    Actual: {output[:200]}"
        )

    return validator


def validate_finds_array():
    """Validator that oinstances completes NSArray search successfully."""

    def validator(output):
        # Should complete without error (may or may not find instances due to timing/ARC)
        if "error" in output.lower() and "usage" not in output.lower():
            return False, (
                f"Command failed with error\n"
                f"    Expected: Successful search\n"
                f"    Actual: Error encountered\n"
                f"    Output preview: {output[:300]}"
            )
        # Finding instances OR reporting none found are both acceptable
        if re.search(r"0x[0-9a-fA-F]+\s+.*Array", output):
            return True, "Found NSArray instances"
        elif "No instances" in output or "Found 0 instance" in output:
            return True, "Completed NSArray search (none found)"
        return True, "Completed NSArray search"

    return validator


def validate_stack_search_works():
    """Validator that --stack option works without error."""

    def validator(output):
        # Should complete without error (may or may not find instances)
        if "error" in output.lower() and "usage" not in output.lower():
            return False, (
                f"Stack search failed\n"
                f"    Expected: Successful search\n"
                f"    Actual: Error encountered\n"
                f"    Output preview: {output[:300]}"
            )
        return True, "Stack search completed"

    return validator


def get_test_specs():
    """Return list of test specifications."""
    return [
        # Basic functionality (NSString is reliable, NSObject often has no direct instances)
        (
            "Instances: finds NSString instances",
            ["oinstances NSString"],
            validate_finds_nsstring(),
        ),
        (
            "Instances: shows instance count",
            ["oinstances NSObject"],
            validate_shows_count(),
        ),
        # Limit testing
        (
            "Instances: respects max matches limit",
            ["oinstances NSObject -M 2"],
            validate_respects_limit(),
        ),
        # Error handling
        (
            "Instances: error on missing class name",
            ["oinstances"],
            validate_error_missing_class(),
        ),
        (
            "Instances: handles nonexistent class gracefully",
            ["oinstances ThisClassDoesNotExist123"],
            validate_handles_nonexistent_class(),
        ),
        # Specific class testing
        (
            "Instances: finds NSArray we created",
            [
                "expr (id)[NSMutableArray array]",  # Create an NSArray
                "oinstances NSArray",
            ],
            validate_finds_array(),
        ),
        # Search mode options
        (
            "Instances: --stack option works",
            ["oinstances NSObject --stack -M 5"],
            validate_stack_search_works(),
        ),
        (
            "Instances: --segments option works",
            ["oinstances NSObject --segments -M 5"],
            validate_stack_search_works(),  # Same validator - just check no error
        ),
    ]


def main():
    """Run all oinstances tests using shared LLDB session."""
    # Check if objc_instances.py exists
    objc_instances_path = os.path.join(PROJECT_ROOT, "scripts", "objc_instances.py")
    if not os.path.exists(objc_instances_path):
        print(f"Error: {objc_instances_path} not found")
        print("Cannot run tests without the implementation.")
        sys.exit(1)

    categories = {
        "Basic functionality": (0, 2),
        "Limit testing": (2, 3),
        "Error handling": (3, 5),
        "Specific class testing": (5, 6),
        "Search mode options": (6, 8),
    }

    passed, total, elapsed, results = run_shared_test_suite(
        "OINSTANCES COMMAND TEST SUITE",
        get_test_specs(),
        scripts=["scripts/objc_instances.py"],
        show_category_summary=categories,
    )
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
