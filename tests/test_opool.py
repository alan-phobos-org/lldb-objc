#!/usr/bin/env python3
"""
Test script for the opool command (Autorelease Pool Scanner).

This script tests the opool functionality:
- Find instances of a class in autorelease pools
- Display address and description

Uses a shared LLDB session for faster test execution.
"""

import sys
import re
import os
from test_helpers import (
    TestResult, check_hello_world_binary, run_shared_test_suite,
    PROJECT_ROOT
)


# =============================================================================
# Validator Functions
# =============================================================================

def validate_finds_inline_data():
    """Validator that opool finds _NSInlineData from autorelease pool."""
    def validator(output):
        # Should find the _NSInlineData instance that's in the autorelease pool
        if '0x' in output and ('nsinlinedata' in output.lower() or 'found' in output.lower()):
            return True, "Found _NSInlineData instance"
        elif 'no instances' in output.lower() or 'not found' in output.lower():
            return False, (f"No instances found\n"
                          f"    Expected: _NSInlineData instance from autorelease pool\n"
                          f"    Actual: No instances reported\n"
                          f"    Output preview: {output[:300]}")
        return False, (f"Unexpected output format\n"
                      f"    Expected: Address and _NSInlineData info\n"
                      f"    Actual: Pattern not found\n"
                      f"    Output preview: {output[:300]}")
    return validator


def validate_finds_constant_date():
    """Validator for NSConstantDate (distantPast)."""
    def validator(output):
        # Should find NSConstantDate with year 0001
        if '0x' in output and ('0001-01-01' in output or 'NSConstantDate' in output):
            return True, "Found NSConstantDate instance"
        elif 'no instances' in output.lower():
            return False, (f"No instances found\n"
                          f"    Expected: NSConstantDate with year 0001\n"
                          f"    Actual: No instances reported\n"
                          f"    Output preview: {output[:300]}")
        return False, (f"Unexpected output format\n"
                      f"    Expected: Address and NSConstantDate with year 0001\n"
                      f"    Actual: Pattern not found\n"
                      f"    Output preview: {output[:300]}")
    return validator


def validate_no_instances_for_nonexistent_class():
    """Validator for class that has no instances in pools."""
    def validator(output):
        # Should gracefully handle classes with no instances in autorelease pools
        if 'no instances' in output.lower() or 'not found' in output.lower() or output.strip() == '':
            return True, "Properly reports no instances"
        # Some output formats might just show nothing
        if '0x' not in output:
            return True, "No instances shown (acceptable)"
        return False, (f"Unexpected output for class with no instances\n"
                      f"    Expected: 'no instances' or empty output\n"
                      f"    Actual: Got unexpected content\n"
                      f"    Output preview: {output[:300]}")
    return validator


def validate_invalid_class_error():
    """Validator for non-existent class."""
    def validator(output):
        if 'not found' in output.lower() or 'error' in output.lower() or 'unknown class' in output.lower():
            return True, "Properly reports error for invalid class"
        # Empty output is also acceptable - no instances found
        if output.strip() == '':
            return True, "No output for invalid class (acceptable)"
        # "No instances" message is also acceptable
        if 'no instances' in output.lower():
            return True, "Reports no instances found (acceptable)"
        return False, (f"Should report error for invalid class\n"
                      f"    Expected: Error message, empty output, or 'no instances'\n"
                      f"    Actual: {output[:200]}")
    return validator


def get_test_specs():
    """Return list of test specifications."""
    return [
        # Regression test for NSConstantDate (distantPast/distantFuture)
        (
            "Find NSConstantDate instances (distantPast)",
            [
                'ocall +[NSDate distantPast]',
                'opool NSDate'
            ],
            validate_finds_constant_date()
        ),
        # Regression test for autorelease pool bug
        (
            "Find _NSInlineData from autorelease pool",
            [
                'ocall malloc(0x1000)',  # Allocate memory
                'ocall [NSData dataWithBytes:$0 length:0x1000]',  # Creates _NSInlineData in pool
                'opool _NSInlineData'
            ],
            validate_finds_inline_data()
        ),
        # Error handling
        (
            "Error: class with no instances in pools",
            ['opool NSFileHandle'],
            validate_no_instances_for_nonexistent_class()
        ),
        (
            "Error: invalid class name",
            ['opool NonExistentClass999'],
            validate_invalid_class_error()
        ),
    ]


def main():
    """Run all opool tests using shared LLDB session."""
    # Check if objc_pool.py exists
    objc_pool_path = os.path.join(PROJECT_ROOT, 'objc_pool.py')
    if not os.path.exists(objc_pool_path):
        print(f"Note: {objc_pool_path} not found")
        print("These tests are for the opool feature.")
        print("Tests will fail until the feature is implemented.\n")

    categories = {
        "NSConstantDate regression": (0, 1),
        "Autorelease pool": (1, 2),
        "Error handling": (2, 4),
    }

    passed, total = run_shared_test_suite(
        "OPOOL COMMAND TEST SUITE",
        get_test_specs(),
        scripts=['objc_pool.py'],
        show_category_summary=categories
    )
    sys.exit(0 if passed == total else 1)


if __name__ == '__main__':
    main()
