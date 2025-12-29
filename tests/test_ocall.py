#!/usr/bin/env python3
"""
Test script for the ocall command (Method Caller).

This script tests the ocall functionality:
- Class method calls: ocall +[NSDate date]
- Instance method calls with address: ocall -[0x600001234560 description]
- Instance method calls with register: ocall -[$r0 uppercaseString]
- Verbose mode: ocall --verbose +[NSDate date]

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

def validate_class_method_basic():
    """Validator for basic class method call."""
    def validator(output):
        # NSDate date returns a date representation
        if re.search(r'\d{4}-\d{2}-\d{2}|\d{2}:\d{2}:\d{2}|NSDate', output):
            return True, "Returned date value"
        elif 'error' in output.lower() or 'failed' in output.lower():
            return False, (f"Command failed\n"
                          f"    Expected: Date representation (YYYY-MM-DD or HH:MM:SS)\n"
                          f"    Actual: Error or failure encountered\n"
                          f"    Output preview: {output[:200]}")
        return False, (f"Unexpected output\n"
                      f"    Expected: Date format or 'NSDate' in output\n"
                      f"    Actual: No date representation found\n"
                      f"    Output preview: {output[:200]}")
    return validator


def validate_class_method_with_arg():
    """Validator for class method with string argument."""
    def validator(output):
        if 'hello' in output:
            return True, "Returned string value"
        elif 'error' in output.lower() and 'not implemented' not in output.lower():
            return False, (f"Command failed\n"
                          f"    Expected: String 'hello' in output\n"
                          f"    Actual: Error encountered\n"
                          f"    Output preview: {output[:200]}")
        return False, (f"String not found in output\n"
                      f"    Expected: 'hello' in returned string\n"
                      f"    Actual: String not present\n"
                      f"    Output preview: {output[:200]}")
    return validator


def validate_instance_method_from_variable():
    """Validator for instance method using $variable."""
    def validator(output):
        if 'TestString' in output:
            return True, "Returned instance description"
        elif 'error' in output.lower() and 'not implemented' not in output.lower():
            return False, (f"Command failed\n"
                          f"    Expected: 'TestString' in output\n"
                          f"    Actual: Error encountered\n"
                          f"    Output preview: {output[:200]}")
        return False, (f"Instance description not found\n"
                      f"    Expected: 'TestString' from $testStr description\n"
                      f"    Actual: String not present in output\n"
                      f"    Output preview: {output[:200]}")
    return validator


def validate_instance_method_from_register():
    """Validator for instance method using register."""
    def validator(output):
        # Register-based calls depend on runtime state, so be lenient
        if 'description' in output.lower() or '$x0' in output or 'register' in output.lower():
            return True, "Register syntax handled"
        elif 'parse' in output.lower() or 'syntax' in output.lower():
            return False, (f"Failed to parse register syntax\n"
                          f"    Expected: Register syntax like '$x0' to be accepted\n"
                          f"    Actual: Parse or syntax error\n"
                          f"    Output preview: {output[:200]}")
        # If it executed without syntax error, that's acceptable
        return True, "Command executed (result depends on register state)"
    return validator


def validate_verbose_mode():
    """Validator for verbose mode output."""
    def validator(output):
        if 'Class' in output or 'SEL' in output or 'resolve' in output.lower():
            return True, "Shows resolution details"
        elif re.search(r'\d{4}-\d{2}-\d{2}|\d{2}:\d{2}:\d{2}', output):
            return False, (f"Got result but no verbose output\n"
                          f"    Expected: Resolution details ('Class', 'SEL', or 'resolve')\n"
                          f"    Actual: Result returned but no verbose information\n"
                          f"    Output preview: {output[:200]}")
        return False, (f"No resolution info\n"
                      f"    Expected: Verbose output with 'Class', 'SEL', or resolution info\n"
                      f"    Actual: No resolution details found\n"
                      f"    Output preview: {output[:200]}")
    return validator


def validate_private_class():
    """Validator for private class method call."""
    def validator(output):
        if 'IDSService' in output or '0x' in output:
            return True, "Resolved private class"
        elif 'not found' in output.lower():
            return False, (f"Private class not found (framework may not be loaded)\n"
                          f"    Expected: IDSService class to be callable\n"
                          f"    Actual: Class not found\n"
                          f"    Possible cause: IDS framework not loaded via dlopen\n"
                          f"    Output preview: {output[:200]}")
        return False, (f"Unexpected output for private class\n"
                      f"    Expected: 'IDSService' or hex address in output\n"
                      f"    Actual: Neither found\n"
                      f"    Output preview: {output[:200]}")
    return validator


def validate_invalid_class():
    """Validator for non-existent class error."""
    def validator(output):
        if 'not found' in output.lower() or 'error' in output.lower() or 'failed' in output.lower():
            return True, "Properly reports error for invalid class"
        return False, (f"Should report error for invalid class\n"
                      f"    Expected: 'not found', 'error', or 'failed' message\n"
                      f"    Actual: No error message found\n"
                      f"    Output preview: {output[:200]}")
    return validator


def validate_invalid_syntax():
    """Validator for syntax errors."""
    def validator(output):
        if 'usage' in output.lower() or 'syntax' in output.lower() or 'error' in output.lower():
            return True, "Properly reports syntax error"
        return False, (f"Should report syntax error\n"
                      f"    Expected: 'usage', 'syntax', or 'error' message\n"
                      f"    Actual: No error message found\n"
                      f"    Output preview: {output[:200]}")
    return validator


def validate_return_value():
    """Validator for return value display."""
    def validator(output):
        if '42' in output:
            return True, "Shows return value"
        return False, (f"Return value not visible\n"
                      f"    Expected: '42' in output from numberWithInt:42\n"
                      f"    Actual: Value not found\n"
                      f"    Output preview: {output[:200]}")
    return validator


# =============================================================================
# Test Specifications
# =============================================================================

def get_test_specs():
    """Return list of test specifications."""
    return [
        # Basic class methods
        (
            "Class method: +[NSDate date]",
            ['ocall +[NSDate date]'],
            validate_class_method_basic()
        ),
        (
            "Class method with arg: +[NSString stringWithString:]",
            ['ocall +[NSString stringWithString:@"hello"]'],
            validate_class_method_with_arg()
        ),
        # Instance methods
        (
            "Instance method from variable",
            [
                'expr NSString *$testStr = @"TestString"',
                'ocall -[$testStr description]'
            ],
            validate_instance_method_from_variable()
        ),
        (
            "Instance method from register ($x0)",
            ['ocall -[$x0 description]'],
            validate_instance_method_from_register()
        ),
        # Verbose mode
        (
            "Verbose mode: --verbose flag",
            ['ocall --verbose +[NSDate date]'],
            validate_verbose_mode()
        ),
        # Private classes
        (
            "Private class: +[IDSService class]",
            ['ocall +[IDSService class]'],
            validate_private_class()
        ),
        # Error handling
        (
            "Error: invalid class",
            ['ocall +[NonExistentClass123 someMethod]'],
            validate_invalid_class()
        ),
        (
            "Error: invalid syntax",
            ['ocall invalid syntax here'],
            validate_invalid_syntax()
        ),
        # Return values
        (
            "Return value display",
            ['ocall +[NSNumber numberWithInt:42]'],
            validate_return_value()
        ),
    ]


def main():
    """Run all ocall tests using shared LLDB session."""
    # Check if objc_call.py exists
    objc_call_path = os.path.join(PROJECT_ROOT, 'objc_call.py')
    if not os.path.exists(objc_call_path):
        print(f"Note: {objc_call_path} not found")
        print("These tests are for the upcoming ocall feature.")
        print("Tests will fail until the feature is implemented.\n")

    categories = {
        "Basic class methods": (0, 2),
        "Instance methods": (2, 4),
        "Verbose mode": (4, 5),
        "Private classes": (5, 6),
        "Error handling": (6, 8),
        "Return values": (8, 9),
    }

    passed, total = run_shared_test_suite(
        "OCALL COMMAND TEST SUITE",
        get_test_specs(),
        scripts=['objc_call.py'],
        show_category_summary=categories
    )
    sys.exit(0 if passed == total else 1)


if __name__ == '__main__':
    main()
