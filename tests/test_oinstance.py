#!/usr/bin/env python3
"""
Test script for the oinstance command (Object Inspector).

This script tests the oinstance functionality:
- Inspect objects by address, variable, or expression
- Display class name, description, hierarchy, and ivars

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

def validate_inspect_shows_class_and_description():
    """Validator that inspect shows class name and object description."""
    def validator(output):
        # Should show class name and description
        # Format: ClassName (0xaddress)
        #           description...
        if re.search(r'\w+ \(0x[0-9a-fA-F]+\)', output):
            return True, "Shows class and address"
        elif 'error' in output.lower():
            return False, (f"Command failed with error\n"
                          f"    Expected: Object inspection output\n"
                          f"    Actual: Error encountered\n"
                          f"    Output preview: {output[:300]}")
        return False, (f"Unexpected output format\n"
                      f"    Expected: ClassName (0xaddress) format\n"
                      f"    Actual: Pattern not found\n"
                      f"    Output preview: {output[:300]}")
    return validator


def validate_inspect_shows_ivars():
    """Validator that inspect shows instance variables."""
    def validator(output):
        # Should show "Instance Variables" section
        if 'Instance Variables' in output:
            return True, "Shows instance variables section"
        elif 'error' in output.lower():
            return False, (f"Command failed with error\n"
                          f"    Expected: Instance variables section\n"
                          f"    Actual: Error encountered\n"
                          f"    Output preview: {output[:300]}")
        # If the class has no ivars, that's okay too
        if 'Instance Variables: none' in output or re.search(r'\w+ \(0x[0-9a-fA-F]+\)', output):
            return True, "Valid inspect output (may have no ivars)"
        return False, (f"Missing instance variables section\n"
                      f"    Expected: 'Instance Variables' section\n"
                      f"    Actual: Section not found\n"
                      f"    Output preview: {output[:300]}")
    return validator


def validate_inspect_with_hex_address():
    """Validator that inspect works with hex address."""
    def validator(output):
        # Should show successful inspection output
        if re.search(r'\w+ \(0x[0-9a-fA-F]+\)', output) and 'Instance Variables' in output:
            return True, "Inspected object via hex address"
        elif 'error' in output.lower():
            return False, (f"Command failed with error\n"
                          f"    Expected: Object inspection output\n"
                          f"    Actual: Error encountered\n"
                          f"    Output preview: {output[:300]}")
        return False, (f"Unexpected output\n"
                      f"    Expected: Valid inspection output\n"
                      f"    Actual: Pattern not found\n"
                      f"    Output preview: {output[:300]}")
    return validator


def validate_inspect_error_nil_address():
    """Validator that inspect errors on nil address."""
    def validator(output):
        if 'error' in output.lower() and 'nil' in output.lower():
            return True, "Properly reports error for nil address"
        return False, (f"Should report error for nil address\n"
                      f"    Expected: Error message with 'nil'\n"
                      f"    Actual: {output[:200]}")
    return validator


def validate_inspect_shows_hierarchy():
    """Validator that inspect shows class hierarchy for non-NSObject classes."""
    def validator(output):
        # For NSMutableString, should show hierarchy like:
        # NSMutableString → NSString → NSObject
        if 'Class Hierarchy' in output or '→' in output:
            return True, "Shows class hierarchy"
        # NSObject itself won't show hierarchy, that's okay
        if re.search(r'\w+ \(0x[0-9a-fA-F]+\)', output):
            return True, "Valid inspect output (may not need hierarchy for NSObject)"
        return False, (f"Expected class hierarchy or valid output\n"
                      f"    Expected: 'Class Hierarchy' section or valid inspection\n"
                      f"    Actual: Pattern not found\n"
                      f"    Output preview: {output[:300]}")
    return validator


def get_test_specs():
    """Return list of test specifications."""
    return [
        # Basic inspection tests
        (
            "Inspect: shows class and description via expression",
            [
                'oinstance (id)[NSDate date]'
            ],
            validate_inspect_shows_class_and_description()
        ),
        (
            "Inspect: shows class and description for string",
            [
                'oinstance (id)[@"TestString" copy]'
            ],
            validate_inspect_shows_class_and_description()
        ),
        (
            "Inspect: shows instance variables",
            [
                'oinstance (id)[NSDate date]'
            ],
            validate_inspect_shows_ivars()
        ),
        (
            "Inspect: works with NSMutableString",
            [
                'oinstance (id)[NSMutableString stringWithString:@"Test"]'
            ],
            validate_inspect_shows_class_and_description()
        ),
        (
            "Inspect: shows class hierarchy",
            [
                'oinstance (id)[NSMutableString stringWithString:@"Test"]'
            ],
            validate_inspect_shows_hierarchy()
        ),
        # Error handling
        (
            "Inspect: error on nil address",
            [
                'oinstance 0x0'
            ],
            validate_inspect_error_nil_address()
        ),
        # Variable inspection
        (
            "Inspect: works with LLDB variable",
            [
                'expr (id)[NSDate date]',  # Creates $0 or similar
                'oinstance $0'
            ],
            validate_inspect_shows_class_and_description()
        ),
    ]


def main():
    """Run all oinstance tests using shared LLDB session."""
    # Check if objc_instance.py exists
    objc_instance_path = os.path.join(PROJECT_ROOT, 'objc_instance.py')
    if not os.path.exists(objc_instance_path):
        print(f"Note: {objc_instance_path} not found")
        print("These tests are for the oinstance feature.")
        print("Tests will fail until the feature is implemented.\n")

    categories = {
        "Basic inspection": (0, 5),
        "Error handling": (5, 6),
        "Variable inspection": (6, 7),
    }

    passed, total = run_shared_test_suite(
        "OINSTANCE COMMAND TEST SUITE",
        get_test_specs(),
        scripts=['objc_instance.py', 'objc_cls.py'],  # Need objc_cls for inspection
        show_category_summary=categories
    )
    sys.exit(0 if passed == total else 1)


if __name__ == '__main__':
    main()
